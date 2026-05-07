"""roma-sim CLI.

Week-2 surface:
    run        — execute one simulation, persist to the run store
    sweep      — Cartesian-product seeds × dispatchers × params, multiprocess
    compare    — aggregate KPI table across a sweep (or a list of run_ids)
    runs       — list recent runs
    sweeps     — list recorded sweeps
    show       — pretty-print one run's metadata + KPIs
    list-dispatchers / list-scenarios

Replay and visual viewer are deferred to Week 3.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from roma_sim.analysis import compute_kpis
from roma_sim.dispatchers import available_dispatchers, get_dispatcher
from roma_sim.domain.events import EventKind
from roma_sim.engine import RunResult
from roma_sim.engine import run as engine_run
from roma_sim.runs import RunStore, SweepConfig, run_sweep
from roma_sim.runs.compare import aggregate_for_sweep
from roma_sim.runs.sweep import parse_param_grid, parse_seeds
from roma_sim.scenarios import get_scenario

app = typer.Typer(
    name="roma-sim",
    help="Roma autonomous-construction simulator (internal R&D).",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


def _humanize_seconds(s: float) -> str:
    if s < 60:
        return f"{s:.1f}s"
    if s < 3600:
        return f"{s / 60:.1f}m"
    if s < 86400:
        return f"{s / 3600:.2f}h"
    return f"{s / 86400:.2f}d"


def _summarize(result: RunResult, kpis: dict) -> Table:
    table = Table(title="Run summary", show_lines=False)
    table.add_column("metric", style="bold")
    table.add_column("value")
    table.add_row("scenario", f"{result.scenario_name} v{result.scenario_version}")
    table.add_row("dispatcher", f"{result.dispatcher_name} v{result.dispatcher_version}")
    table.add_row("seed", str(result.seed))
    table.add_row("makespan", _humanize_seconds(result.makespan))
    table.add_row("events", f"{len(result.events):,}")
    if result.final_world is not None:
        tg = result.final_world.tasks
        table.add_row("tasks", f"{len(tg.completed())}/{len(tg.tasks)} completed")
    table.add_row("crew_idle", f"{kpis.get('crew_idle_fraction', 0) * 100:.1f}%")
    table.add_row(
        "throughput", f"{kpis.get('throughput_tasks_per_hour', 0):.2f} tasks/h"
    )
    table.add_row("wall_time", f"{result.wall_seconds:.2f}s")
    table.add_row("completed", "yes" if result.completed else "no")
    return table


@app.command()
def run(
    scenario: str = typer.Option("warehouse_shell", "--scenario", "-s", help="Scenario name."),
    dispatcher: str = typer.Option("greedy", "--dispatcher", "-d", help="Dispatcher name."),
    seed: int = typer.Option(0, "--seed", help="RNG seed."),
    out: Path = typer.Option(Path("runs"), "--out", help="Run store root directory."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress per-event output."),
    also_jsonl: bool = typer.Option(False, "--also-jsonl", help="Also write events.jsonl."),
    max_seconds: float = typer.Option(
        30 * 24 * 3600.0, "--max-seconds", help="Hard simulated-time cutoff."
    ),
    dispatch_interval: float = typer.Option(
        30.0, "--dispatch-interval", help="Seconds between dispatch loop ticks."
    ),
) -> None:
    """Run one simulation and persist it to the run store."""
    scen = get_scenario(scenario)
    disp = get_dispatcher(dispatcher)
    store = RunStore(out)

    if not quiet:
        console.print(
            f"[bold cyan]roma-sim[/] running "
            f"[bold]{scen.name}[/] x [bold]{disp.name}[/] (seed={seed})"
        )

    callback = None
    if not quiet:
        important = {
            EventKind.SIM_START,
            EventKind.SIM_END,
            EventKind.TASK_COMPLETED,
        }

        def _log(ev) -> None:
            if ev.kind in important:
                console.print(
                    f"[dim]{_humanize_seconds(ev.t):>8}[/]  "
                    f"[yellow]{ev.kind.value:<16}[/]  "
                    f"{json.dumps(dict(ev.payload))}"
                )

        callback = _log

    wall_start = time.monotonic()
    result = engine_run(
        scen,
        disp,
        seed=seed,
        max_sim_seconds=max_seconds,
        dispatch_interval=dispatch_interval,
        on_event=callback,
    )
    wall = time.monotonic() - wall_start

    fleet = result.final_world.fleet if result.final_world is not None else None
    kpis = compute_kpis(result.events, fleet).as_flat_dict() if fleet is not None else {}

    record = store.write_run(
        scenario_name=result.scenario_name,
        scenario_version=result.scenario_version,
        dispatcher_name=result.dispatcher_name,
        dispatcher_version=result.dispatcher_version,
        seed=result.seed,
        params={},
        kpis=kpis,
        events=result.events,
        wall_seconds=wall,
        completed=result.completed,
        also_jsonl=also_jsonl,
    )

    console.print(_summarize(result, kpis))
    console.print(f"[green]wrote run[/] {record.run_id}")


@app.command()
def sweep(
    scenario: str = typer.Option("warehouse_shell", "--scenario", "-s"),
    dispatchers: str = typer.Option(
        "greedy,critical_path", "--dispatchers", help="Comma-separated dispatcher names."
    ),
    seeds: str = typer.Option("0:10", "--seeds", help="Range '0:50' or list '0,1,2'."),
    param: list[str] = typer.Option(
        [], "--param", "-p", help="Repeatable: 'key=v1,v2,v3'."
    ),
    workers: int = typer.Option(1, "--workers", "-w", help="Parallel workers."),
    out: Path = typer.Option(Path("runs"), "--out", help="Run store root directory."),
    description: str = typer.Option("", "--desc", help="Free-text description."),
    dispatch_interval: float = typer.Option(30.0, "--dispatch-interval"),
    max_seconds: float = typer.Option(30 * 24 * 3600.0, "--max-seconds"),
    also_jsonl: bool = typer.Option(False, "--also-jsonl"),
) -> None:
    """Cartesian-product sweep across (dispatcher, params, seed). Multiprocess."""
    config = SweepConfig(
        scenario_name=scenario,
        dispatchers=[d.strip() for d in dispatchers.split(",") if d.strip()],
        seeds=parse_seeds(seeds),
        scenario_param_grid=parse_param_grid(param),
        workers=workers,
        description=description,
        dispatch_interval=dispatch_interval,
        max_sim_seconds=max_seconds,
    )
    store = RunStore(out)
    n_cells = len(config.cells())

    console.print(
        f"[bold cyan]sweep[/] {scenario} | "
        f"{len(config.dispatchers)} dispatchers x "
        f"{max(1, len(parse_param_grid(param)) or 1)} param-grid x "
        f"{len(config.seeds)} seeds = "
        f"[bold]{n_cells}[/] cells, workers={workers}"
    )

    state = {"done": 0}

    def progress(out: dict) -> None:
        state["done"] += 1
        if out.get("ok"):
            rec = out["record"]
            console.print(
                f"[dim]{state['done']:>4}/{n_cells}[/] "
                f"{rec['dispatcher_name']:<14} "
                f"seed={rec['seed']:<3} "
                f"params={rec['params']} "
                f"makespan={rec['makespan_s'] / 3600:.2f}h"
            )
        else:
            console.print(
                f"[red]{state['done']:>4}/{n_cells} FAIL {out.get('error')}[/]"
            )

    result = run_sweep(config, store, also_jsonl=also_jsonl, progress=progress)

    console.print()
    console.print(
        f"[green]sweep complete[/] sweep_id=[bold]{result.sweep_id}[/] "
        f"ok={result.n_succeeded}/{result.n_cells} "
        f"failed={result.n_failed} "
        f"wall={result.wall_seconds:.1f}s"
    )
    if result.failures:
        for args, err in result.failures[:5]:
            console.print(f"  [red]fail[/] {args} -> {err}")


@app.command()
def compare(
    sweep_id: Optional[str] = typer.Option(None, "--sweep", help="Sweep id to aggregate."),
    runs: Optional[str] = typer.Option(
        None, "--runs", help="Comma-separated run_ids (alt. to --sweep)."
    ),
    out: Path = typer.Option(Path("runs"), "--out", help="Run store root directory."),
) -> None:
    """Print a KPI comparison table across runs."""
    store = RunStore(out)
    if sweep_id is None and runs is None:
        sweeps = store.list_sweeps()
        if not sweeps:
            console.print("[red]no sweeps in the store[/]")
            raise typer.Exit(1)
        sweep_id = sweeps[0]["sweep_id"]
        console.print(f"[dim]using most recent sweep_id={sweep_id}[/]")

    rows = aggregate_for_sweep(
        store,
        sweep_id=sweep_id,
        run_ids=[r.strip() for r in runs.split(",")] if runs else None,
    )
    if not rows:
        console.print("[red]no runs matched[/]")
        raise typer.Exit(1)

    table = Table(title=f"compare sweep={sweep_id or 'manual'}", show_lines=False)
    table.add_column("dispatcher", style="bold")
    table.add_column("params")
    table.add_column("n", justify="right")
    table.add_column("done", justify="right")
    table.add_column("makespan_p50", justify="right")
    table.add_column("makespan_p95", justify="right")
    table.add_column("crew_idle_%", justify="right")
    table.add_column("tasks/h", justify="right")
    table.add_column("cycle_p50", justify="right")

    rows.sort(key=lambda r: (r.param_label(), r.makespan_h_p50))
    for r in rows:
        table.add_row(
            r.dispatcher,
            r.param_label(),
            str(r.n_runs),
            str(r.n_completed),
            f"{r.makespan_h_p50:.2f}h",
            f"{r.makespan_h_p95:.2f}h",
            f"{r.crew_idle_pct:.1f}%",
            f"{r.throughput_tasks_per_h:.2f}",
            _humanize_seconds(r.cycle_time_p50_s),
        )
    console.print(table)


@app.command("runs")
def runs_(
    sweep_id: Optional[str] = typer.Option(None, "--sweep"),
    limit: int = typer.Option(20, "--limit"),
    out: Path = typer.Option(Path("runs"), "--out"),
) -> None:
    """List recent runs in the store."""
    store = RunStore(out)
    records = store.list_runs(sweep_id=sweep_id, limit=limit)
    if not records:
        console.print("[dim]no runs[/]")
        return
    table = Table(title="runs")
    table.add_column("run_id")
    table.add_column("scenario")
    table.add_column("dispatcher")
    table.add_column("seed", justify="right")
    table.add_column("makespan", justify="right")
    table.add_column("done", justify="center")
    for r in records:
        table.add_row(
            r.run_id,
            r.scenario_name,
            r.dispatcher_name,
            str(r.seed),
            _humanize_seconds(r.makespan_s),
            "yes" if r.completed else "no",
        )
    console.print(table)


@app.command()
def sweeps(
    out: Path = typer.Option(Path("runs"), "--out"),
) -> None:
    """List recorded sweeps in the store."""
    store = RunStore(out)
    rows = store.list_sweeps()
    if not rows:
        console.print("[dim]no sweeps[/]")
        return
    table = Table(title="sweeps")
    table.add_column("sweep_id")
    table.add_column("created")
    table.add_column("description")
    for r in rows:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(r["created_at"])))
        table.add_row(r["sweep_id"], ts, r["description"] or "")
    console.print(table)


@app.command()
def show(
    run_id: str = typer.Argument(..., help="run_id to show."),
    out: Path = typer.Option(Path("runs"), "--out"),
) -> None:
    """Show one run's metadata + KPIs."""
    store = RunStore(out)
    rec = store.get_run(run_id)
    if rec is None:
        console.print(f"[red]unknown run_id {run_id}[/]")
        raise typer.Exit(1)

    table = Table(title=run_id)
    table.add_column("field", style="bold")
    table.add_column("value")
    table.add_row("scenario", f"{rec.scenario_name} v{rec.scenario_version}")
    table.add_row("dispatcher", f"{rec.dispatcher_name} v{rec.dispatcher_version}")
    table.add_row("seed", str(rec.seed))
    table.add_row("params", json.dumps(rec.params))
    table.add_row("makespan", _humanize_seconds(rec.makespan_s))
    table.add_row("events", str(rec.n_events))
    table.add_row("completed", "yes" if rec.completed else "no")
    table.add_row("wall_seconds", f"{rec.wall_seconds:.2f}")
    table.add_row("events_path", rec.events_path)
    console.print(table)
    console.print("[bold]KPIs:[/]")
    console.print(json.dumps(rec.kpis, indent=2, sort_keys=True))


@app.command("list-dispatchers")
def list_dispatchers() -> None:
    """List available dispatchers."""
    table = Table(title="Dispatchers")
    table.add_column("name")
    table.add_column("version")
    for d in available_dispatchers():
        table.add_row(d.name, d.version)
    console.print(table)


@app.command("list-scenarios")
def list_scenarios() -> None:
    """List available scenarios."""
    from roma_sim.scenarios.warehouse_shell import WarehouseShellScenario

    table = Table(title="Scenarios")
    table.add_column("name")
    table.add_column("version")
    s = WarehouseShellScenario()
    table.add_row(s.name, s.version)
    console.print(table)


if __name__ == "__main__":
    app()
