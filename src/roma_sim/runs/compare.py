"""Compare runs across a sweep.

Group runs by (dispatcher, scenario_params), then aggregate KPI distributions
across seeds. The output is the table the plan called for:

    dispatcher       fleet_size  makespan_p50  crew_idle_%  panels_per_day
    greedy           3           14.2d         31%          8.1
    critical_path    3           11.8d         22%          9.4
    ilp              3           11.5d         18%          9.5
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from roma_sim.runs.store import RunRecord, RunStore


@dataclass
class CompareRow:
    dispatcher: str
    params: dict[str, Any]
    n_runs: int
    n_completed: int
    makespan_h_p50: float
    makespan_h_p95: float
    crew_idle_pct: float
    throughput_tasks_per_h: float
    cycle_time_p50_s: float

    def param_label(self) -> str:
        if not self.params:
            return "(default)"
        return " ".join(f"{k}={v}" for k, v in sorted(self.params.items()))


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def _mean(xs: list[float]) -> float:
    return statistics.fmean(xs) if xs else 0.0


def aggregate(runs: Iterable[RunRecord]) -> list[CompareRow]:
    """Group by (dispatcher, params) and compute summary stats."""
    runs = list(runs)
    groups: dict[tuple[str, str], list[RunRecord]] = {}
    for r in runs:
        key = (r.dispatcher_name, json.dumps(r.params, sort_keys=True))
        groups.setdefault(key, []).append(r)

    rows: list[CompareRow] = []
    for (dispatcher, params_key), grp in groups.items():
        params = json.loads(params_key)
        completed = [r for r in grp if r.completed]
        makespan_h = [r.makespan_s / 3600.0 for r in completed]
        idle_pcts = [
            float(r.kpis.get("crew_idle_fraction", 0.0)) * 100.0 for r in completed
        ]
        throughputs = [
            float(r.kpis.get("throughput_tasks_per_hour", 0.0)) for r in completed
        ]
        cycle_p50s = [float(r.kpis.get("cycle_time_p50_s", 0.0)) for r in completed]

        rows.append(
            CompareRow(
                dispatcher=dispatcher,
                params=params,
                n_runs=len(grp),
                n_completed=len(completed),
                makespan_h_p50=_percentile(makespan_h, 50.0),
                makespan_h_p95=_percentile(makespan_h, 95.0),
                crew_idle_pct=_mean(idle_pcts),
                throughput_tasks_per_h=_mean(throughputs),
                cycle_time_p50_s=_mean(cycle_p50s),
            )
        )

    rows.sort(key=lambda r: (r.param_label(), r.dispatcher))
    return rows


def fetch_runs_for_sweep(store: RunStore, sweep_id: str) -> list[RunRecord]:
    return store.list_runs(sweep_id=sweep_id)


def fetch_runs_by_ids(store: RunStore, run_ids: list[str]) -> list[RunRecord]:
    out: list[RunRecord] = []
    for rid in run_ids:
        rec = store.get_run(rid)
        if rec is None:
            raise KeyError(f"unknown run_id {rid!r}")
        out.append(rec)
    return out


def aggregate_for_sweep(
    store: RunStore,
    sweep_id: Optional[str] = None,
    run_ids: Optional[list[str]] = None,
) -> list[CompareRow]:
    if sweep_id is not None:
        return aggregate(fetch_runs_for_sweep(store, sweep_id))
    if run_ids is not None:
        return aggregate(fetch_runs_by_ids(store, run_ids))
    raise ValueError("must provide either sweep_id or run_ids")
