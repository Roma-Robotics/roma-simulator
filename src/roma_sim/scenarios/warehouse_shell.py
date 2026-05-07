"""Warehouse-shell scenario.

A simplified tilt-up warehouse build: pour the slab, lift precast panels into
place, install panels, then finish. The DAG is intentionally shallow so the
greedy dispatcher actually works on it; it'll get more interesting once the
critical-path and ILP dispatchers land in Week 2+.

Topology
--------
A 100m x 60m site with five named zones:

    +----------------+----------------+
    |   STAGING      |   PANEL_YARD   |
    +----------------+----------------+
    |          SLAB (work area)       |
    +----------------+----------------+
    |   LIFT_BAY     |   FINISHING    |
    +----------------+----------------+

Skills
------
- pour:    slab pours
- lift:    panel lift / placement (the crane bot)
- install: bolt-up & bracing crew
- finish:  joint sealing, paint, punch

Tunables
--------
- panel_count:   how many panels around the slab perimeter (default 12).
- pour_count:    how many pour bots in the fleet (default 2).
- lift_count:    how many lift bots (default 1).
- install_count: how many install crews (default 2).
- finish_count:  how many finishers (default 1).
"""

from __future__ import annotations

from dataclasses import dataclass

from roma_sim.domain import (
    Agent,
    AgentState,
    Fleet,
    Site,
    Task,
    TaskGraph,
    Zone,
)


@dataclass(frozen=True)
class WarehouseShellScenario:
    name: str = "warehouse_shell"
    version: str = "0.1.0"
    panel_count: int = 12
    pour_count: int = 2
    lift_count: int = 1
    install_count: int = 2
    finish_count: int = 1

    def build(self) -> tuple[Site, TaskGraph, Fleet]:
        site = _build_site()
        tasks = _build_tasks(self.panel_count)
        fleet = _build_fleet(
            pour_count=self.pour_count,
            lift_count=self.lift_count,
            install_count=self.install_count,
            finish_count=self.finish_count,
            site=site,
        )
        return site, tasks, fleet


def _build_site() -> Site:
    zones = (
        Zone(id="staging", name="Staging", x=0.0, y=40.0, width=50.0, height=20.0),
        Zone(id="panel_yard", name="Panel Yard", x=50.0, y=40.0, width=50.0, height=20.0),
        Zone(id="slab", name="Slab", x=0.0, y=20.0, width=100.0, height=20.0),
        Zone(id="lift_bay", name="Lift Bay", x=0.0, y=0.0, width=50.0, height=20.0),
        Zone(id="finishing", name="Finishing", x=50.0, y=0.0, width=50.0, height=20.0),
    )
    return Site(name="warehouse_shell", width=100.0, height=60.0, zones=zones)


def _build_tasks(panel_count: int) -> TaskGraph:
    tasks: list[Task] = []

    pour_a = Task(
        id="pour_a",
        name="Pour slab section A",
        skill="pour",
        zone_id="slab",
        duration_mean=4 * 3600.0,
        duration_std=20 * 60.0,
        deps=(),
    )
    pour_b = Task(
        id="pour_b",
        name="Pour slab section B",
        skill="pour",
        zone_id="slab",
        duration_mean=4 * 3600.0,
        duration_std=20 * 60.0,
        deps=(),
    )
    cure = Task(
        id="cure",
        name="Cure slab",
        skill="pour",
        zone_id="slab",
        duration_mean=8 * 3600.0,
        duration_std=15 * 60.0,
        deps=("pour_a", "pour_b"),
    )
    tasks += [pour_a, pour_b, cure]

    lift_ids: list[str] = []
    install_ids: list[str] = []
    for i in range(panel_count):
        lift_id = f"lift_p{i:02d}"
        install_id = f"install_p{i:02d}"
        lift_ids.append(lift_id)
        install_ids.append(install_id)
        tasks.append(
            Task(
                id=lift_id,
                name=f"Lift panel {i:02d}",
                skill="lift",
                zone_id="panel_yard",
                duration_mean=20 * 60.0,
                duration_std=4 * 60.0,
                deps=("cure",),
            )
        )
        tasks.append(
            Task(
                id=install_id,
                name=f"Install panel {i:02d}",
                skill="install",
                zone_id="lift_bay",
                duration_mean=35 * 60.0,
                duration_std=8 * 60.0,
                deps=(lift_id,),
            )
        )

    finish = Task(
        id="finish",
        name="Finish & punch",
        skill="finish",
        zone_id="finishing",
        duration_mean=6 * 3600.0,
        duration_std=30 * 60.0,
        deps=tuple(install_ids),
    )
    tasks.append(finish)

    return TaskGraph(tasks=tuple(tasks))


def _build_fleet(
    pour_count: int,
    lift_count: int,
    install_count: int,
    finish_count: int,
    site: Site,
) -> Fleet:
    staging = site.zone("staging").centroid
    panel_yard = site.zone("panel_yard").centroid
    lift_bay = site.zone("lift_bay").centroid
    finishing = site.zone("finishing").centroid

    agents: list[AgentState] = []

    def add(skill: str, count: int, home: tuple[float, float], speed: float, prefix: str) -> None:
        for i in range(count):
            agent = Agent(
                id=f"{prefix}_{i:02d}",
                name=f"{prefix.title()} bot {i:02d}",
                skills=frozenset({skill}),
                speed_mps=speed,
                home_x=home[0],
                home_y=home[1],
            )
            agents.append(AgentState(agent=agent, x=home[0], y=home[1]))

    add("pour", pour_count, staging, speed=0.8, prefix="pour")
    add("lift", lift_count, panel_yard, speed=0.6, prefix="lift")
    add("install", install_count, lift_bay, speed=1.2, prefix="install")
    add("finish", finish_count, finishing, speed=1.2, prefix="finish")

    return Fleet(agents=tuple(agents))
