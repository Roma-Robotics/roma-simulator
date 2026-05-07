"""Sweep runner tests."""

from __future__ import annotations

from pathlib import Path

from roma_sim.runs import RunStore, SweepConfig, run_sweep
from roma_sim.runs.compare import aggregate_for_sweep
from roma_sim.runs.sweep import parse_param_grid, parse_seeds


def test_parse_seeds() -> None:
    assert parse_seeds("0:5") == [0, 1, 2, 3, 4]
    assert parse_seeds("0,3,7") == [0, 3, 7]
    assert parse_seeds("42") == [42]


def test_parse_param_grid() -> None:
    g = parse_param_grid(["panel_count=2,4", "speed=0.5,1.5"])
    assert g == {"panel_count": [2, 4], "speed": [0.5, 1.5]}


def test_sweep_cells_cartesian() -> None:
    cfg = SweepConfig(
        scenario_name="warehouse_shell",
        dispatchers=["greedy", "critical_path"],
        seeds=[0, 1],
        scenario_param_grid={"panel_count": [4, 6]},
    )
    cells = cfg.cells()
    # 2 dispatchers x 2 param combos x 2 seeds = 8
    assert len(cells) == 8


def test_single_worker_sweep_writes_runs(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    cfg = SweepConfig(
        scenario_name="warehouse_shell",
        dispatchers=["greedy", "critical_path"],
        seeds=[0, 1],
        scenario_param_grid={"panel_count": [3]},
        workers=1,
        dispatch_interval=60.0,
    )
    result = run_sweep(cfg, store)
    assert result.n_failed == 0
    assert result.n_succeeded == 4

    runs = store.list_runs(sweep_id=result.sweep_id)
    assert len(runs) == 4
    assert {r.dispatcher_name for r in runs} == {"greedy", "critical_path"}


def test_compare_aggregates_kpis(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    cfg = SweepConfig(
        scenario_name="warehouse_shell",
        dispatchers=["greedy", "critical_path"],
        seeds=[0, 1, 2],
        scenario_param_grid={"panel_count": [3]},
        workers=1,
        dispatch_interval=60.0,
    )
    result = run_sweep(cfg, store)
    rows = aggregate_for_sweep(store, sweep_id=result.sweep_id)
    assert len(rows) == 2
    by_dispatcher = {r.dispatcher: r for r in rows}
    assert by_dispatcher["greedy"].n_completed == 3
    assert by_dispatcher["critical_path"].n_completed == 3
    assert by_dispatcher["greedy"].makespan_h_p50 > 0
    assert by_dispatcher["critical_path"].makespan_h_p50 > 0
