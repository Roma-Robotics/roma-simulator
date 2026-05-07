"""Replay: reconstruct viewer-ready timelines from an event log.

The event log is the source of truth. Replay turns it into the data shape the
HTML5 viewer wants:

  * For each agent: a list of motion segments (`(t0, t1, x0, y0, x1, y1)`)
    plus task intervals (`(t0, t1, task_id)`).
  * For each task: lifecycle timestamps (`ready_at`, `started_at`,
    `completed_at`, `assigned_to`).
  * The static site geometry, the run identity, and high-level KPIs.

This module is the contract for any future visual layer (browser canvas,
Streamlit, the marketing-page `Simulator.tsx`). Anything that wants to render
a run consumes this exact shape.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Optional

from roma_sim.domain import Event, EventKind, Fleet, Site
from roma_sim.domain.tasks import Task


@dataclass
class AgentTimeline:
    agent_id: str
    name: str
    skill: str
    speed_mps: float
    home_x: float
    home_y: float
    # Motion segments, in chronological order. While outside a segment, the
    # agent is stationary at the previous segment's `(x1, y1)` (or `(home_x,
    # home_y)` before the first segment).
    moves: list[dict[str, Any]] = field(default_factory=list)
    # Periods during which the agent was actively executing a task.
    work: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TaskTimeline:
    task_id: str
    name: str
    skill: str
    zone_id: str
    duration_mean: float
    deps: list[str]
    ready_at: Optional[float] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    assigned_to: Optional[str] = None


def build_agent_timelines(
    events: Iterable[Event], fleet: Fleet
) -> dict[str, AgentTimeline]:
    """Index motion + work segments per agent."""
    timelines: dict[str, AgentTimeline] = {}
    for a in fleet.agents:
        skill = next(iter(a.agent.skills), "unknown")
        timelines[a.id] = AgentTimeline(
            agent_id=a.id,
            name=a.agent.name,
            skill=skill,
            speed_mps=a.agent.speed_mps,
            home_x=a.agent.home_x,
            home_y=a.agent.home_y,
        )

    work_open: dict[str, dict[str, Any]] = {}

    for ev in events:
        kind = ev.kind
        payload = ev.payload
        if kind is EventKind.AGENT_MOVE_START:
            aid = str(payload["agent_id"])
            tl = timelines.get(aid)
            if tl is None:
                continue
            x0, y0 = payload["from"]
            x1, y1 = payload["to"]
            travel_s = float(payload.get("travel_s", 0.0))
            tl.moves.append(
                {
                    "t0": ev.t,
                    "t1": ev.t + travel_s,
                    "x0": float(x0),
                    "y0": float(y0),
                    "x1": float(x1),
                    "y1": float(y1),
                }
            )
        elif kind is EventKind.TASK_STARTED:
            aid = str(payload["agent_id"])
            tid = str(payload["task_id"])
            work_open[aid] = {"t0": ev.t, "task_id": tid}
        elif kind is EventKind.TASK_COMPLETED:
            aid = str(payload["agent_id"])
            tl = timelines.get(aid)
            open_rec = work_open.pop(aid, None)
            if tl is not None and open_rec is not None:
                tl.work.append({**open_rec, "t1": ev.t})

    # Close any still-open work intervals at the last event time.
    last_t = max((ev.t for ev in events), default=0.0)
    for aid, open_rec in work_open.items():
        tl = timelines.get(aid)
        if tl is not None:
            tl.work.append({**open_rec, "t1": last_t})

    return timelines


def build_task_timelines(
    events: Iterable[Event], tasks: Iterable[Task]
) -> dict[str, TaskTimeline]:
    timelines: dict[str, TaskTimeline] = {}
    for t in tasks:
        timelines[t.id] = TaskTimeline(
            task_id=t.id,
            name=t.name,
            skill=t.skill,
            zone_id=t.zone_id,
            duration_mean=t.duration_mean,
            deps=list(t.deps),
        )

    for ev in events:
        payload = ev.payload
        tid = str(payload.get("task_id", ""))
        tl = timelines.get(tid)
        if tl is None:
            continue
        if ev.kind is EventKind.TASK_READY and tl.ready_at is None:
            tl.ready_at = ev.t
        elif ev.kind is EventKind.TASK_ASSIGNED:
            tl.assigned_to = str(payload.get("agent_id", "")) or None
        elif ev.kind is EventKind.TASK_STARTED and tl.started_at is None:
            tl.started_at = ev.t
        elif ev.kind is EventKind.TASK_COMPLETED and tl.completed_at is None:
            tl.completed_at = ev.t

    return timelines


def build_viewer_payload(
    events: list[Event],
    site: Site,
    fleet: Fleet,
    initial_tasks: Iterable[Task],
    *,
    run_id: str,
    scenario_name: str,
    scenario_version: str,
    dispatcher_name: str,
    dispatcher_version: str,
    seed: int,
    kpis: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a JSON-serializable dict the HTML viewer can consume directly."""
    agent_tls = build_agent_timelines(events, fleet)
    task_tls = build_task_timelines(events, initial_tasks)
    makespan = max((ev.t for ev in events), default=0.0)

    return {
        "run_id": run_id,
        "scenario": {"name": scenario_name, "version": scenario_version},
        "dispatcher": {"name": dispatcher_name, "version": dispatcher_version},
        "seed": seed,
        "makespan_s": makespan,
        "kpis": kpis or {},
        "site": {
            "name": site.name,
            "width": site.width,
            "height": site.height,
            "zones": [
                {
                    "id": z.id,
                    "name": z.name,
                    "x": z.x,
                    "y": z.y,
                    "width": z.width,
                    "height": z.height,
                }
                for z in site.zones
            ],
        },
        "agents": [
            {
                "id": tl.agent_id,
                "name": tl.name,
                "skill": tl.skill,
                "speed_mps": tl.speed_mps,
                "home": [tl.home_x, tl.home_y],
                "moves": tl.moves,
                "work": tl.work,
            }
            for tl in agent_tls.values()
        ],
        "tasks": [
            {
                "id": tl.task_id,
                "name": tl.name,
                "skill": tl.skill,
                "zone_id": tl.zone_id,
                "duration_mean": tl.duration_mean,
                "deps": tl.deps,
                "ready_at": tl.ready_at,
                "started_at": tl.started_at,
                "completed_at": tl.completed_at,
                "assigned_to": tl.assigned_to,
            }
            for tl in task_tls.values()
        ],
        "events": [ev.to_json() for ev in events],
    }
