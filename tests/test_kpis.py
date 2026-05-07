"""Tests for KPI computation."""

from __future__ import annotations

from roma_sim.analysis import compute_kpis
from roma_sim.dispatchers.greedy import GreedyNearestDispatcher
from roma_sim.domain import (
    Agent,
    AgentState,
    Event,
    EventKind,
    Fleet,
)
from roma_sim.engine import run
from roma_sim.scenarios.warehouse_shell import WarehouseShellScenario


def _fleet_of(*specs: tuple[str, str]) -> Fleet:
    return Fleet(
        agents=tuple(
            AgentState(
                agent=Agent(
                    id=aid,
                    name=aid,
                    skills=frozenset({skill}),
                    speed_mps=1.0,
                    home_x=0,
                    home_y=0,
                ),
                x=0,
                y=0,
            )
            for aid, skill in specs
        )
    )


def test_idle_fraction_is_one_when_nothing_runs() -> None:
    fleet = _fleet_of(("a1", "x"))
    events = [
        Event(t=0.0, seq=1, kind=EventKind.SIM_START, payload={}),
        Event(t=100.0, seq=2, kind=EventKind.SIM_END, payload={}),
    ]
    k = compute_kpis(events, fleet)
    assert k.crew_idle_fraction == 1.0
    assert k.n_tasks_completed == 0
    assert k.makespan_s == 100.0


def test_idle_fraction_zero_when_agent_busy_throughout() -> None:
    fleet = _fleet_of(("a1", "x"))
    events = [
        Event(t=0.0, seq=1, kind=EventKind.SIM_START, payload={}),
        Event(t=0.0, seq=2, kind=EventKind.AGENT_BUSY, payload={"agent_id": "a1"}),
        Event(t=100.0, seq=3, kind=EventKind.AGENT_IDLE, payload={"agent_id": "a1"}),
        Event(t=100.0, seq=4, kind=EventKind.SIM_END, payload={}),
    ]
    k = compute_kpis(events, fleet)
    assert k.crew_idle_fraction == 0.0
    assert k.per_agent_busy_fraction["a1"] == 1.0


def test_throughput_and_cycle_times() -> None:
    fleet = _fleet_of(("a1", "x"))
    events = [
        Event(t=0.0, seq=1, kind=EventKind.SIM_START, payload={}),
        Event(t=0.0, seq=2, kind=EventKind.TASK_READY, payload={"task_id": "t1"}),
        Event(t=0.0, seq=3, kind=EventKind.TASK_READY, payload={"task_id": "t2"}),
        Event(t=0.0, seq=4, kind=EventKind.TASK_ASSIGNED, payload={"task_id": "t1", "agent_id": "a1"}),
        Event(t=10.0, seq=5, kind=EventKind.TASK_COMPLETED, payload={"task_id": "t1"}),
        Event(t=10.0, seq=6, kind=EventKind.TASK_ASSIGNED, payload={"task_id": "t2", "agent_id": "a1"}),
        Event(t=30.0, seq=7, kind=EventKind.TASK_COMPLETED, payload={"task_id": "t2"}),
        Event(t=3600.0, seq=8, kind=EventKind.SIM_END, payload={}),
    ]
    k = compute_kpis(events, fleet)
    assert k.n_tasks_completed == 2
    assert k.n_tasks_total == 2
    assert k.throughput_tasks_per_hour == 2.0
    assert k.cycle_time_p50_s == 20.0
    assert k.dispatch_decisions == 2


def test_kpis_on_real_run_completes() -> None:
    scen = WarehouseShellScenario(panel_count=4)
    result = run(scen, GreedyNearestDispatcher(), seed=0, dispatch_interval=60.0)
    k = compute_kpis(result.events, result.final_world.fleet)
    assert k.completed
    assert k.makespan_s > 0
    assert 0.0 <= k.crew_idle_fraction <= 1.0
    assert k.n_tasks_completed == k.n_tasks_total
    assert "pour" in k.per_skill_utilization
    assert k.total_travel_m > 0
