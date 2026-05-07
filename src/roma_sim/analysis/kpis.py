"""KPI calculations from event logs.

These are the numbers your fleet engineers will live in. Everything is
computed deterministically from `(events, fleet)` so two runs with the same
event log always produce identical KPIs.

Definitions kept conservative on purpose:
  * `makespan_s` — wall-clock simulated time from sim_start to last completion.
  * `crew_idle_fraction` — fraction of fleet-time agents were idle (not busy
    on a task, not in transit). 1.0 = nobody worked. 0.0 = perfect packing.
  * `*_utilization` — 1 - idle_fraction, per-skill cohort.
  * `throughput_tasks_per_hour` — `n_tasks_completed / (makespan_s / 3600)`.
  * `cycle_time_p50_s` / `cycle_time_p95_s` — median / p95 of
    `(t_complete - t_ready)` for tasks that completed.
  * `total_travel_m` — sum of distances from `agent_move_start` events.
  * `dispatch_decisions` — `task_assigned` count (a noisy proxy for how often
    the dispatch loop fired actionable decisions).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from roma_sim.domain import Event, EventKind, Fleet


@dataclass(frozen=True)
class RunKPIs:
    """KPIs derived from a single run's event log."""

    makespan_s: float
    n_tasks_completed: int
    n_tasks_total: int
    completed: bool
    crew_idle_fraction: float
    throughput_tasks_per_hour: float
    cycle_time_p50_s: float
    cycle_time_p95_s: float
    total_travel_m: float
    dispatch_decisions: int
    per_skill_utilization: dict[str, float] = field(default_factory=dict)
    per_agent_busy_fraction: dict[str, float] = field(default_factory=dict)

    def as_flat_dict(self) -> dict[str, Any]:
        """Flatten to a single-level dict for tabular display / DB columns."""
        out: dict[str, Any] = {
            "makespan_s": self.makespan_s,
            "n_tasks_completed": self.n_tasks_completed,
            "n_tasks_total": self.n_tasks_total,
            "completed": self.completed,
            "crew_idle_fraction": self.crew_idle_fraction,
            "throughput_tasks_per_hour": self.throughput_tasks_per_hour,
            "cycle_time_p50_s": self.cycle_time_p50_s,
            "cycle_time_p95_s": self.cycle_time_p95_s,
            "total_travel_m": self.total_travel_m,
            "dispatch_decisions": self.dispatch_decisions,
        }
        for skill, util in self.per_skill_utilization.items():
            out[f"util_{skill}"] = util
        return out


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile. `pct` in [0, 100]."""
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


def compute_kpis(events: Iterable[Event], fleet: Fleet) -> RunKPIs:
    """Compute KPIs from an event stream and the initial fleet."""
    events = list(events)
    if not events:
        return RunKPIs(
            makespan_s=0.0,
            n_tasks_completed=0,
            n_tasks_total=0,
            completed=False,
            crew_idle_fraction=1.0,
            throughput_tasks_per_hour=0.0,
            cycle_time_p50_s=0.0,
            cycle_time_p95_s=0.0,
            total_travel_m=0.0,
            dispatch_decisions=0,
        )

    t_start = events[0].t
    t_end = events[-1].t
    duration = max(t_end - t_start, 0.0)

    ready_at: dict[str, float] = {}
    completed_at: dict[str, float] = {}
    n_total = 0
    n_completed = 0
    dispatch_decisions = 0
    total_travel_m = 0.0

    # busy_intervals[agent_id] = list of (start, end) seconds
    busy_intervals: dict[str, list[tuple[float, float]]] = {a.id: [] for a in fleet.agents}
    busy_open_at: dict[str, float] = {}

    sim_end_seen = False

    for ev in events:
        if ev.kind is EventKind.TASK_READY:
            tid = str(ev.payload["task_id"])
            ready_at.setdefault(tid, ev.t)
            n_total = max(n_total, len(ready_at))
        elif ev.kind is EventKind.TASK_COMPLETED:
            tid = str(ev.payload["task_id"])
            completed_at[tid] = ev.t
            n_completed += 1
        elif ev.kind is EventKind.TASK_ASSIGNED:
            dispatch_decisions += 1
        elif ev.kind is EventKind.AGENT_BUSY:
            aid = str(ev.payload["agent_id"])
            busy_open_at[aid] = ev.t
        elif ev.kind is EventKind.AGENT_IDLE:
            aid = str(ev.payload["agent_id"])
            start = busy_open_at.pop(aid, None)
            if start is not None:
                busy_intervals.setdefault(aid, []).append((start, ev.t))
        elif ev.kind is EventKind.AGENT_MOVE_START:
            d = ev.payload.get("distance_m")
            if isinstance(d, (int, float)):
                total_travel_m += float(d)
        elif ev.kind is EventKind.SIM_END:
            sim_end_seen = True

    # Close any still-open busy intervals at t_end (e.g. on aborted runs).
    for aid, start in busy_open_at.items():
        busy_intervals.setdefault(aid, []).append((start, t_end))

    # Use the canonical n_total: every task that ever became ready.
    n_total = len(ready_at)

    # Cycle times.
    cycle_times = [
        completed_at[tid] - ready_at[tid] for tid in completed_at if tid in ready_at
    ]

    # Idle fraction across the fleet.
    if duration > 0 and fleet.agents:
        per_agent_busy_s: dict[str, float] = {}
        for agent in fleet.agents:
            intervals = busy_intervals.get(agent.id, [])
            busy_s = sum(max(0.0, e - s) for s, e in intervals)
            per_agent_busy_s[agent.id] = min(busy_s, duration)
        total_busy_s = sum(per_agent_busy_s.values())
        total_capacity_s = duration * len(fleet.agents)
        crew_idle_fraction = max(0.0, 1.0 - total_busy_s / total_capacity_s)
        per_agent_busy_fraction = {
            aid: per_agent_busy_s[aid] / duration for aid in per_agent_busy_s
        }
        # Per-skill utilization: average busy_fraction across agents whose
        # *only* skill is that skill (Week 1 fleet is single-skill per agent).
        per_skill_busy: dict[str, list[float]] = {}
        for agent in fleet.agents:
            for skill in agent.agent.skills:
                per_skill_busy.setdefault(skill, []).append(
                    per_agent_busy_fraction.get(agent.id, 0.0)
                )
        per_skill_util = {s: sum(xs) / len(xs) for s, xs in per_skill_busy.items()}
    else:
        crew_idle_fraction = 1.0
        per_agent_busy_fraction = {a.id: 0.0 for a in fleet.agents}
        per_skill_util = {}

    throughput = (
        (n_completed / (duration / 3600.0)) if duration > 0 else 0.0
    )

    return RunKPIs(
        makespan_s=duration,
        n_tasks_completed=n_completed,
        n_tasks_total=n_total,
        completed=sim_end_seen and n_completed == n_total and n_total > 0,
        crew_idle_fraction=crew_idle_fraction,
        throughput_tasks_per_hour=throughput,
        cycle_time_p50_s=_percentile(cycle_times, 50.0),
        cycle_time_p95_s=_percentile(cycle_times, 95.0),
        total_travel_m=total_travel_m,
        dispatch_decisions=dispatch_decisions,
        per_skill_utilization=per_skill_util,
        per_agent_busy_fraction=per_agent_busy_fraction,
    )
