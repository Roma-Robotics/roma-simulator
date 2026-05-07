"""roma-sim CLI: run one simulation, write the event log to disk.

Week-1 surface: `run` only. `sweep`, `replay`, and `ui` arrive in Week 2.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from roma_sim.dispatchers import get_dispatcher
from roma_sim.domain.events import EventKind
from roma_sim.engine import RunResult
from roma_sim.engine import run as engine_run
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


def _summarize(result: RunResult) -> Table:
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
        table.add_row(
            "tasks",
            f"{len(tg.completed())}/{len(tg.tasks)} completed",
        )
    table.add_row("wall_time", f"{result.wall_seconds:.2f}s")
    table.add_row("completed", "yes" if result.completed else "no")
    return table


def _write_run(result: RunResult, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = (
        f"{int(time.time())}-{result.scenario_name}-{result.dispatcher_name}"
        f"-s{result.seed}"
    )
    run_path = out_dir / run_id
    run_path.mkdir(parents=True, exist_ok=True)

    events_path = run_path / "events.jsonl"
    with events_path.open("w") as f:
        for ev in result.events:
            f.write(json.dumps(ev.to_json()) + "\n")

    meta_path = run_path / "metadata.json"
    with meta_path.open("w") as f:
        json.dump(
            {
                "run_id": run_id,
                "scenario_name": result.scenario_name,
                "scenario_version": result.scenario_version,
                "dispatcher_name": result.dispatcher_name,
                "dispatcher_version": result.dispatcher_version,
                "seed": result.seed,
                "makespan_s": result.makespan,
                "wall_seconds": result.wall_seconds,
                "n_events": len(result.events),
                "completed": result.completed,
            },
            f,
            indent=2,
        )
    return run_path


@app.command()
def run(
    scenario: str = typer.Option("warehouse_shell", "--scenario", "-s", help="Scenario name."),
    dispatcher: str = typer.Option("greedy", "--dispatcher", "-d", help="Dispatcher name."),
    seed: int = typer.Option(0, "--seed", help="RNG seed."),
    out: Path = typer.Option(Path("runs"), "--out", help="Output directory for run artifacts."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress per-event output."),
    max_seconds: float = typer.Option(
        30 * 24 * 3600.0,
        "--max-seconds",
        help="Hard simulated-time cutoff.",
    ),
    dispatch_interval: float = typer.Option(
        30.0,
        "--dispatch-interval",
        help="Seconds between dispatch loop ticks.",
    ),
) -> None:
    """Run one simulation and write the event log to disk."""
    scen = get_scenario(scenario)
    disp = get_dispatcher(dispatcher)

    if not quiet:
        console.print(
            f"[bold cyan]roma-sim[/] running "
            f"[bold]{scen.name}[/] x [bold]{disp.name}[/] (seed={seed})"
        )

    callback: Optional[object] = None
    if not quiet and os.isatty(1):
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

    result = engine_run(
        scen,
        disp,
        seed=seed,
        max_sim_seconds=max_seconds,
        dispatch_interval=dispatch_interval,
        on_event=callback,  # type: ignore[arg-type]
    )

    run_path = _write_run(result, out)
    console.print(_summarize(result))
    console.print(f"[green]wrote run to[/] {run_path}")


@app.command()
def list_dispatchers() -> None:
    """List available dispatchers."""
    from roma_sim.dispatchers.greedy import GreedyNearestDispatcher

    table = Table(title="Dispatchers")
    table.add_column("name")
    table.add_column("version")
    g = GreedyNearestDispatcher()
    table.add_row(g.name, g.version)
    console.print(table)


@app.command()
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
