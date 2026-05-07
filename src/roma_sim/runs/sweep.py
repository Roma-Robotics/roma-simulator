"""Multiprocess sweep runner.

Cartesian-product `(seeds × dispatchers × scenario_param_grid)` and execute
each cell in its own subprocess. Each run is independent: per-seed
deterministic, no shared state. Results land in the run store under one
sweep_id so `roma-sim compare` can aggregate them.

We intentionally use top-level worker functions and pickle-friendly inputs
(strings, ints, dicts) rather than passing live objects across the pool —
that's the path of least resistance for `multiprocessing` across platforms.
"""

from __future__ import annotations

import itertools
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from roma_sim.analysis import compute_kpis
from roma_sim.dispatchers import get_dispatcher
from roma_sim.engine import run as engine_run
from roma_sim.runs.store import RunRecord, RunStore
from roma_sim.scenarios import get_scenario


@dataclass
class SweepConfig:
    """Spec for a single sweep run."""

    scenario_name: str
    dispatchers: list[str]
    seeds: list[int]
    scenario_param_grid: dict[str, list[Any]] = field(default_factory=dict)
    workers: int = 1
    description: str = ""
    dispatch_interval: float = 30.0
    max_sim_seconds: float = 30 * 24 * 3600.0

    def cells(self) -> list[dict[str, Any]]:
        """Expand the configuration into one dict per (dispatcher, params, seed)."""
        keys = list(self.scenario_param_grid.keys())
        value_lists = [self.scenario_param_grid[k] for k in keys]
        param_combos: list[dict[str, Any]] = []
        if keys:
            for combo in itertools.product(*value_lists):
                param_combos.append(dict(zip(keys, combo)))
        else:
            param_combos.append({})

        cells: list[dict[str, Any]] = []
        for dispatcher in self.dispatchers:
            for params in param_combos:
                for seed in self.seeds:
                    cells.append(
                        {
                            "scenario_name": self.scenario_name,
                            "dispatcher_name": dispatcher,
                            "params": params,
                            "seed": seed,
                        }
                    )
        return cells


@dataclass
class SweepResult:
    sweep_id: str
    n_cells: int
    n_succeeded: int
    n_failed: int
    wall_seconds: float
    failures: list[tuple[dict[str, Any], str]] = field(default_factory=list)


def _execute_cell(args: dict[str, Any]) -> dict[str, Any]:
    """Worker entry point. MUST stay pickle-friendly and import-light.

    Inputs are plain dicts; output is a serialized RunRecord-shaped dict.
    Any exception is caught and surfaced via `error`.
    """
    try:
        scen = get_scenario(args["scenario_name"], **args["params"])
        disp = get_dispatcher(args["dispatcher_name"])
        wall_start = time.monotonic()
        result = engine_run(
            scen,
            disp,
            seed=args["seed"],
            dispatch_interval=args["dispatch_interval"],
            max_sim_seconds=args["max_sim_seconds"],
        )
        wall = time.monotonic() - wall_start
        kpis = compute_kpis(result.events, result.final_world.fleet).as_flat_dict() \
            if result.final_world is not None else {}
        store = RunStore(Path(args["store_root"]))
        record = store.write_run(
            scenario_name=result.scenario_name,
            scenario_version=result.scenario_version,
            dispatcher_name=result.dispatcher_name,
            dispatcher_version=result.dispatcher_version,
            seed=result.seed,
            params=args["params"],
            kpis=kpis,
            events=result.events,
            wall_seconds=wall,
            completed=result.completed,
            sweep_id=args["sweep_id"],
            also_jsonl=args.get("also_jsonl", False),
        )
        return {"ok": True, "record": asdict(record)}
    except Exception as ex:  # noqa: BLE001 -- surface any failure to caller
        return {
            "ok": False,
            "error": f"{type(ex).__name__}: {ex}",
            "args": {k: v for k, v in args.items() if k != "store_root"},
        }


def run_sweep(
    config: SweepConfig,
    store: RunStore,
    also_jsonl: bool = False,
    progress: Optional[Any] = None,
) -> SweepResult:
    """Execute a sweep. Blocks until every cell finishes (or fails)."""
    cells = config.cells()
    sweep_id = store.new_sweep(config.description)

    args_list = [
        {
            **c,
            "sweep_id": sweep_id,
            "store_root": str(store.root),
            "dispatch_interval": config.dispatch_interval,
            "max_sim_seconds": config.max_sim_seconds,
            "also_jsonl": also_jsonl,
        }
        for c in cells
    ]

    wall_start = time.monotonic()
    succeeded = 0
    failures: list[tuple[dict[str, Any], str]] = []

    workers = max(1, config.workers)
    if workers == 1:
        for a in args_list:
            out = _execute_cell(a)
            if out.get("ok"):
                succeeded += 1
            else:
                failures.append((out["args"], out["error"]))
            if progress is not None:
                progress(out)
    else:
        cpu = os.cpu_count() or 1
        max_workers = min(workers, cpu, len(args_list))
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_execute_cell, a): a for a in args_list}
            for fut in as_completed(futures):
                out = fut.result()
                if out.get("ok"):
                    succeeded += 1
                else:
                    failures.append((out.get("args", {}), out.get("error", "unknown")))
                if progress is not None:
                    progress(out)

    return SweepResult(
        sweep_id=sweep_id,
        n_cells=len(args_list),
        n_succeeded=succeeded,
        n_failed=len(failures),
        wall_seconds=time.monotonic() - wall_start,
        failures=failures,
    )


def parse_seeds(spec: str) -> list[int]:
    """Parse `--seeds` syntax: `0:50`, `0,1,2`, or `7`."""
    spec = spec.strip()
    if ":" in spec:
        a, b = spec.split(":", 1)
        return list(range(int(a), int(b)))
    if "," in spec:
        return [int(x) for x in spec.split(",")]
    return [int(spec)]


def parse_param_grid(specs: list[str]) -> dict[str, list[Any]]:
    """Parse one or more `--param key=v1,v2,v3` flags.

    Values are coerced via int -> float -> str in that order.
    """
    grid: dict[str, list[Any]] = {}
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"bad --param {spec!r}; expected key=v1,v2,...")
        key, raw = spec.split("=", 1)
        values: list[Any] = []
        for tok in raw.split(","):
            tok = tok.strip()
            try:
                values.append(int(tok))
                continue
            except ValueError:
                pass
            try:
                values.append(float(tok))
                continue
            except ValueError:
                pass
            values.append(tok)
        grid[key.strip()] = values
    return grid
