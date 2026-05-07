"""Snapshot-style tests on the warehouse-shell scenario.

These don't pin the exact KPIs; they pin the *shape* of the world, and the
fact that a greedy run completes. The Week-3 regression suite will pin
distributions across seeds.
"""

from __future__ import annotations

import pytest

from roma_sim.dispatchers.greedy import GreedyNearestDispatcher
from roma_sim.engine import run
from roma_sim.scenarios.warehouse_shell import WarehouseShellScenario


def test_scenario_builds() -> None:
    site, tasks, fleet = WarehouseShellScenario().build()
    assert site.name == "warehouse_shell"
    assert len(site.zones) == 5
    assert len(tasks.tasks) >= 4  # pour_a, pour_b, cure, finish, plus panels
    assert all(a.id for a in fleet.agents)


def test_task_graph_is_acyclic_dag_with_finish_terminal() -> None:
    _, tasks, _ = WarehouseShellScenario(panel_count=4).build()
    finish = tasks.by_id("finish")
    assert "install_p00" in finish.deps
    assert "install_p03" in finish.deps


@pytest.mark.parametrize("seed", [0, 1, 7])
def test_greedy_run_completes(seed: int) -> None:
    scen = WarehouseShellScenario(panel_count=4)
    result = run(scen, GreedyNearestDispatcher(), seed=seed, dispatch_interval=60.0)
    assert result.completed, f"run did not complete for seed={seed}"
    assert result.makespan > 0
    assert result.final_world is not None
    assert result.final_world.tasks.is_done()


def test_run_is_seed_reproducible() -> None:
    scen = WarehouseShellScenario(panel_count=4)
    r1 = run(scen, GreedyNearestDispatcher(), seed=42, dispatch_interval=60.0)
    r2 = run(scen, GreedyNearestDispatcher(), seed=42, dispatch_interval=60.0)
    assert r1.makespan == r2.makespan
    assert len(r1.events) == len(r2.events)
    for a, b in zip(r1.events, r2.events):
        assert a.t == b.t
        assert a.kind == b.kind
        assert a.payload == b.payload


def test_different_seeds_yield_different_event_logs() -> None:
    scen = WarehouseShellScenario(panel_count=4)
    r1 = run(scen, GreedyNearestDispatcher(), seed=1, dispatch_interval=60.0)
    r2 = run(scen, GreedyNearestDispatcher(), seed=2, dispatch_interval=60.0)
    # Stochastic durations should diverge somewhere.
    assert r1.makespan != r2.makespan or any(
        a.payload != b.payload for a, b in zip(r1.events, r2.events)
    )
