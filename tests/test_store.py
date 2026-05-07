"""Run-store tests."""

from __future__ import annotations

from pathlib import Path

from roma_sim.analysis import compute_kpis
from roma_sim.dispatchers.greedy import GreedyNearestDispatcher
from roma_sim.engine import run
from roma_sim.runs import RunStore
from roma_sim.scenarios.warehouse_shell import WarehouseShellScenario


def _do_run(seed: int = 0):
    scen = WarehouseShellScenario(panel_count=4)
    return run(scen, GreedyNearestDispatcher(), seed=seed, dispatch_interval=60.0)


def test_store_roundtrip(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    result = _do_run()
    kpis = compute_kpis(result.events, result.final_world.fleet).as_flat_dict()
    record = store.write_run(
        scenario_name=result.scenario_name,
        scenario_version=result.scenario_version,
        dispatcher_name=result.dispatcher_name,
        dispatcher_version=result.dispatcher_version,
        seed=result.seed,
        params={"panel_count": 4},
        kpis=kpis,
        events=result.events,
        wall_seconds=0.5,
        completed=result.completed,
    )
    fetched = store.get_run(record.run_id)
    assert fetched is not None
    assert fetched.run_id == record.run_id
    assert fetched.params == {"panel_count": 4}
    assert fetched.kpis["throughput_tasks_per_hour"] == kpis["throughput_tasks_per_hour"]
    assert fetched.completed


def test_load_events_returns_byte_equal_log(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    result = _do_run()
    kpis = compute_kpis(result.events, result.final_world.fleet).as_flat_dict()
    record = store.write_run(
        scenario_name=result.scenario_name,
        scenario_version=result.scenario_version,
        dispatcher_name=result.dispatcher_name,
        dispatcher_version=result.dispatcher_version,
        seed=result.seed,
        params={},
        kpis=kpis,
        events=result.events,
        wall_seconds=0.5,
        completed=result.completed,
    )
    loaded = store.load_events(record.run_id)
    assert len(loaded) == len(result.events)
    for a, b in zip(loaded, result.events):
        assert a.t == b.t
        assert a.seq == b.seq
        assert a.kind == b.kind
        assert a.payload == b.payload


def test_sweep_id_links_runs(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    sweep_id = store.new_sweep("test sweep")
    for seed in (0, 1, 2):
        result = _do_run(seed=seed)
        kpis = compute_kpis(result.events, result.final_world.fleet).as_flat_dict()
        store.write_run(
            scenario_name=result.scenario_name,
            scenario_version=result.scenario_version,
            dispatcher_name=result.dispatcher_name,
            dispatcher_version=result.dispatcher_version,
            seed=seed,
            params={},
            kpis=kpis,
            events=result.events,
            wall_seconds=0.1,
            completed=result.completed,
            sweep_id=sweep_id,
        )
    runs = store.list_runs(sweep_id=sweep_id)
    assert len(runs) == 3
    assert {r.seed for r in runs} == {0, 1, 2}


def test_list_sweeps(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    s1 = store.new_sweep("first")
    s2 = store.new_sweep("second")
    sweeps = store.list_sweeps()
    ids = {s["sweep_id"] for s in sweeps}
    assert s1 in ids and s2 in ids
