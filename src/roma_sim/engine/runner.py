"""SimPy-backed event-driven runner.

Tier 1.5: discrete events for task durations, with a 2D constant-speed
travel model on top so spatial conflicts (two agents trying to be in the
same place) are observable, not invisible.

The runner is pure: given `(scenario, dispatcher, seed)` it returns a
`RunResult`. No I/O. Persistence is the run-store layer's job.
"""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field, replace
from typing import Callable, Protocol

import simpy

from roma_sim.dispatchers.base import Dispatcher
from roma_sim.domain import (
    AgentState,
    Assignment,
    Event,
    EventKind,
    Fleet,
    Site,
    Task,
    TaskGraph,
    TaskStatus,
    World,
)
from roma_sim.domain.site import euclidean
from roma_sim.engine.stochastics import DurationSampler, make_rng

log = logging.getLogger(__name__)


class Scenario(Protocol):
    """A scenario yields the initial world plus identity for the run record."""

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def build(self) -> tuple[Site, TaskGraph, Fleet]: ...


@dataclass
class RunResult:
    """Outcome of a run.

    Attributes:
        scenario_name:      e.g. "warehouse_shell".
        scenario_version:   scenario semver, used for reproducibility.
        dispatcher_name:    e.g. "greedy".
        dispatcher_version: dispatcher semver.
        seed:               RNG seed.
        events:             ordered event log (the durable artifact).
        final_world:        terminal World snapshot.
        wall_seconds:       real time the run took (informational only).
    """

    scenario_name: str
    scenario_version: str
    dispatcher_name: str
    dispatcher_version: str
    seed: int
    events: list[Event] = field(default_factory=list)
    final_world: World | None = None
    wall_seconds: float = 0.0
    completed: bool = False

    @property
    def makespan(self) -> float:
        if not self.events:
            return 0.0
        return max(e.t for e in self.events)


def _validate_assignments(
    assignments: list[Assignment],
    ready: list[Task],
    idle: list[AgentState],
) -> list[Assignment]:
    """Drop any assignment that violates the contract; warn for visibility."""
    ready_index = {t.id: t for t in ready}
    idle_index = {a.id: a for a in idle}
    seen_agents: set[str] = set()
    seen_tasks: set[str] = set()
    valid: list[Assignment] = []
    for a in assignments:
        if a.agent_id in seen_agents:
            log.warning("dispatcher reused agent %s; dropping", a.agent_id)
            continue
        if a.task_id in seen_tasks:
            log.warning("dispatcher reused task %s; dropping", a.task_id)
            continue
        if a.agent_id not in idle_index:
            log.warning("dispatcher assigned non-idle agent %s; dropping", a.agent_id)
            continue
        if a.task_id not in ready_index:
            log.warning("dispatcher assigned non-ready task %s; dropping", a.task_id)
            continue
        agent = idle_index[a.agent_id]
        task = ready_index[a.task_id]
        if not agent.can_perform(task.skill):
            log.warning(
                "agent %s lacks skill %s for task %s; dropping",
                a.agent_id,
                task.skill,
                a.task_id,
            )
            continue
        seen_agents.add(a.agent_id)
        seen_tasks.add(a.task_id)
        valid.append(a)
    return valid


def run(
    scenario: Scenario,
    dispatcher: Dispatcher,
    seed: int = 0,
    max_sim_seconds: float = 30 * 24 * 3600.0,
    dispatch_interval: float = 30.0,
    on_event: Callable[[Event], None] | None = None,
) -> RunResult:
    """Execute one simulation run.

    Args:
        scenario:          scenario instance (provides Site, TaskGraph, Fleet).
        dispatcher:        policy under test.
        seed:              RNG seed for stochastic durations.
        max_sim_seconds:   hard simulated-time cutoff (safety net).
        dispatch_interval: how often the dispatch loop wakes if no event fires.
        on_event:          optional callback for streaming events as they occur.
    """
    wall_start = _time.monotonic()
    site, task_graph, fleet = scenario.build()
    task_graph = task_graph.mark_ready()

    env = simpy.Environment()
    rng = make_rng(seed)
    sampler = DurationSampler(rng)

    state = {"tasks": task_graph, "fleet": fleet}
    events: list[Event] = []
    seq = {"n": 0}
    signal = {"e": env.event()}
    announced_ready: set[str] = set()

    def emit(kind: EventKind, payload: dict | None = None) -> Event:
        seq["n"] += 1
        ev = Event(t=float(env.now), seq=seq["n"], kind=kind, payload=payload or {})
        events.append(ev)
        if on_event is not None:
            on_event(ev)
        return ev

    def announce_ready(graph: TaskGraph) -> None:
        for t in graph.tasks:
            if t.status is TaskStatus.READY and t.id not in announced_ready:
                announced_ready.add(t.id)
                emit(EventKind.TASK_READY, {"task_id": t.id, "name": t.name})

    def snapshot() -> World:
        return World(
            t=float(env.now),
            site=site,
            tasks=state["tasks"],  # type: ignore[arg-type]
            fleet=state["fleet"],  # type: ignore[arg-type]
        )

    def kick_dispatch() -> None:
        sig = signal["e"]
        if not sig.triggered:
            sig.succeed()
        signal["e"] = env.event()

    def _execute(a: Assignment):
        tasks: TaskGraph = state["tasks"]  # type: ignore[assignment]
        fleet_state: Fleet = state["fleet"]  # type: ignore[assignment]
        task = tasks.by_id(a.task_id)
        agent_state = fleet_state.by_id(a.agent_id)

        new_task = replace(task, status=TaskStatus.IN_PROGRESS, assigned_to=a.agent_id)
        new_agent = replace(agent_state, busy=True, current_task=task.id)
        state["tasks"] = tasks.replace_task(new_task)
        state["fleet"] = fleet_state.replace_agent(new_agent)
        emit(EventKind.TASK_ASSIGNED, {"task_id": task.id, "agent_id": agent_state.id})
        emit(EventKind.AGENT_BUSY, {"agent_id": agent_state.id, "task_id": task.id})

        zone = site.zone(task.zone_id)
        target = zone.centroid
        dist = euclidean(agent_state.position, target)
        speed = max(agent_state.agent.speed_mps, 1e-6)
        travel_time = dist / speed
        if travel_time > 0:
            emit(
                EventKind.AGENT_MOVE_START,
                {
                    "agent_id": agent_state.id,
                    "from": list(agent_state.position),
                    "to": list(target),
                    "distance_m": dist,
                    "travel_s": travel_time,
                },
            )
            yield env.timeout(travel_time)
            fleet_now: Fleet = state["fleet"]  # type: ignore[assignment]
            state["fleet"] = fleet_now.with_position(agent_state.id, target[0], target[1])
            emit(EventKind.AGENT_MOVE_END, {"agent_id": agent_state.id, "at": list(target)})

        duration = sampler.sample(task.duration_mean, task.duration_std)
        emit(
            EventKind.TASK_STARTED,
            {"task_id": task.id, "agent_id": agent_state.id, "duration_s": duration},
        )
        yield env.timeout(duration)

        tasks_now: TaskGraph = state["tasks"]  # type: ignore[assignment]
        fleet_now2: Fleet = state["fleet"]  # type: ignore[assignment]
        completed_task = replace(
            tasks_now.by_id(task.id), status=TaskStatus.COMPLETED, assigned_to=None
        )
        idle_agent = replace(
            fleet_now2.by_id(agent_state.id), busy=False, current_task=None
        )
        new_graph = tasks_now.replace_task(completed_task).mark_ready()
        state["tasks"] = new_graph
        state["fleet"] = fleet_now2.replace_agent(idle_agent)
        emit(
            EventKind.TASK_COMPLETED,
            {"task_id": task.id, "agent_id": agent_state.id, "t_finish": float(env.now)},
        )
        announce_ready(new_graph)
        emit(EventKind.AGENT_IDLE, {"agent_id": agent_state.id})
        kick_dispatch()

    def dispatch_loop():
        emit(
            EventKind.SIM_START,
            {
                "scenario": scenario.name,
                "scenario_version": scenario.version,
                "dispatcher": dispatcher.name,
                "dispatcher_version": dispatcher.version,
                "seed": seed,
            },
        )
        announce_ready(state["tasks"])  # type: ignore[arg-type]
        emit(EventKind.TICK, {"phase": "init"})

        while True:
            tasks: TaskGraph = state["tasks"]  # type: ignore[assignment]
            fleet_state: Fleet = state["fleet"]  # type: ignore[assignment]
            if tasks.is_done():
                break
            if env.now >= max_sim_seconds:
                log.warning("hit max_sim_seconds=%s; aborting", max_sim_seconds)
                break

            world = snapshot()
            ready = tasks.ready()
            idle = fleet_state.idle()
            if ready and idle:
                proposed = list(dispatcher.assign(world, ready, idle))
                valid = _validate_assignments(proposed, ready, idle)
                for a in valid:
                    env.process(_execute(a))

            timeout = env.timeout(dispatch_interval)
            sig = signal["e"]
            yield simpy.AnyOf(env, [timeout, sig])
            emit(EventKind.TICK, {"phase": "dispatch"})

        emit(EventKind.SIM_END, {"makespan_s": float(env.now)})

    proc = env.process(dispatch_loop())
    env.run(until=proc)

    final = snapshot()
    return RunResult(
        scenario_name=scenario.name,
        scenario_version=scenario.version,
        dispatcher_name=dispatcher.name,
        dispatcher_version=dispatcher.version,
        seed=seed,
        events=events,
        final_world=final,
        wall_seconds=_time.monotonic() - wall_start,
        completed=final.tasks.is_done(),
    )
