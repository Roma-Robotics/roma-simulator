"""Property tests on engine invariants.

Hypothesis-style randomized tests that say things like "no matter what seed
you pick, the DAG order is respected". When these break, your dispatcher or
your engine has a bug.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from roma_sim.dispatchers.greedy import GreedyNearestDispatcher
from roma_sim.domain import EventKind
from roma_sim.engine import run
from roma_sim.scenarios.warehouse_shell import WarehouseShellScenario


@given(seed=st.integers(min_value=0, max_value=10_000))
@settings(
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_dag_order_respected(seed: int) -> None:
    """Every TASK_STARTED for task T comes after TASK_COMPLETED of every dep of T."""
    scen = WarehouseShellScenario(panel_count=3)
    result = run(scen, GreedyNearestDispatcher(), seed=seed, dispatch_interval=60.0)
    assert result.completed

    started_at: dict[str, float] = {}
    completed_at: dict[str, float] = {}
    for ev in result.events:
        if ev.kind is EventKind.TASK_STARTED:
            started_at[ev.payload["task_id"]] = ev.t
        elif ev.kind is EventKind.TASK_COMPLETED:
            completed_at[ev.payload["task_id"]] = ev.t

    _, tasks, _ = scen.build()
    for t in tasks.tasks:
        if not t.deps:
            continue
        assert t.id in started_at, f"task {t.id} never started"
        for dep in t.deps:
            assert dep in completed_at, f"dep {dep} never completed"
            assert completed_at[dep] <= started_at[t.id] + 1e-9, (
                f"task {t.id} started at {started_at[t.id]} before "
                f"dep {dep} completed at {completed_at[dep]}"
            )


@given(seed=st.integers(min_value=0, max_value=10_000))
@settings(
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_one_task_per_agent_at_a_time(seed: int) -> None:
    """An agent never holds two TASK_ASSIGNED records without a TASK_COMPLETED between them."""
    scen = WarehouseShellScenario(panel_count=3)
    result = run(scen, GreedyNearestDispatcher(), seed=seed, dispatch_interval=60.0)

    holding: dict[str, str] = {}
    for ev in result.events:
        if ev.kind is EventKind.TASK_ASSIGNED:
            agent = ev.payload["agent_id"]
            assert agent not in holding, (
                f"agent {agent} got task {ev.payload['task_id']} while still "
                f"holding {holding.get(agent)}"
            )
            holding[agent] = ev.payload["task_id"]
        elif ev.kind is EventKind.TASK_COMPLETED:
            agent = ev.payload["agent_id"]
            assert holding.pop(agent, None) == ev.payload["task_id"]


@given(seed=st.integers(min_value=0, max_value=10_000))
@settings(
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_event_seq_is_monotonic(seed: int) -> None:
    scen = WarehouseShellScenario(panel_count=3)
    result = run(scen, GreedyNearestDispatcher(), seed=seed, dispatch_interval=60.0)
    seqs = [e.seq for e in result.events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


@given(seed=st.integers(min_value=0, max_value=10_000))
@settings(
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_event_time_is_non_decreasing(seed: int) -> None:
    scen = WarehouseShellScenario(panel_count=3)
    result = run(scen, GreedyNearestDispatcher(), seed=seed, dispatch_interval=60.0)
    times = [e.t for e in result.events]
    assert all(b >= a for a, b in zip(times, times[1:]))
