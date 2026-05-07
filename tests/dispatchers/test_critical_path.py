"""Critical-path dispatcher unit tests + a head-to-head with greedy."""

from __future__ import annotations

from roma_sim.dispatchers.critical_path import (
    CriticalPathDispatcher,
    _longest_remaining_path,
)
from roma_sim.dispatchers.greedy import GreedyNearestDispatcher
from roma_sim.domain import (
    Agent,
    AgentState,
    Fleet,
    Site,
    Task,
    TaskGraph,
    TaskStatus,
    World,
    Zone,
)
from roma_sim.engine import run as engine_run
from roma_sim.scenarios.warehouse_shell import WarehouseShellScenario


def _site() -> Site:
    return Site(
        name="t",
        width=100,
        height=100,
        zones=(
            Zone(id="a", name="A", x=0, y=0, width=10, height=10),
            Zone(id="b", name="B", x=80, y=80, width=10, height=10),
        ),
    )


def _agent(aid: str, x: float, y: float, skill: str = "x") -> AgentState:
    return AgentState(
        agent=Agent(
            id=aid,
            name=aid,
            skills=frozenset({skill}),
            speed_mps=1.0,
            home_x=x,
            home_y=y,
        ),
        x=x,
        y=y,
    )


def _task(tid: str, mean: float, deps=()) -> Task:
    return Task(
        id=tid,
        name=tid,
        skill="x",
        zone_id="a",
        duration_mean=mean,
        duration_std=0.0,
        deps=tuple(deps),
        status=TaskStatus.READY if not deps else TaskStatus.PENDING,
    )


def test_longest_path_picks_longer_chain() -> None:
    # graph:    short(10) -> tail
    #           long_a(50) -> long_b(50) -> tail
    # tail has 0 mean, so longest_remaining(short) = 10 and longest_remaining(long_a) = 100.
    g = TaskGraph(
        tasks=(
            _task("short", 10.0),
            _task("long_a", 50.0),
            _task("long_b", 50.0, deps=("long_a",)),
            _task("tail", 1.0, deps=("short", "long_b")),
        )
    )
    cp = _longest_remaining_path(g)
    assert cp["long_a"] > cp["short"]
    assert cp["short"] > cp["tail"]


def test_critical_path_prefers_longer_chain_first() -> None:
    site = _site()
    a = _agent("a1", 0, 0)
    g = TaskGraph(
        tasks=(
            _task("short", 10.0),
            _task("long_a", 50.0),
            _task("tail", 1.0, deps=("short", "long_a")),
        )
    )
    g = g.mark_ready()
    world = World(t=0.0, site=site, tasks=g, fleet=Fleet(agents=(a,)))
    out = CriticalPathDispatcher().assign(world, g.ready(), [a])
    assert len(out) == 1
    assert out[0].task_id == "long_a"


def test_critical_path_beats_or_ties_greedy_on_warehouse_shell() -> None:
    """The shell DAG has finish gating on every install, so CP should help.

    Across 5 seeds, CP's median makespan must be <= greedy's. Hard equality
    is too strict (sometimes they tie when fleet caps are the bottleneck);
    we just check CP is never worse on average.
    """
    seeds = list(range(5))
    greedy_makespans = []
    cp_makespans = []
    for seed in seeds:
        scen = WarehouseShellScenario(panel_count=6)
        g = engine_run(scen, GreedyNearestDispatcher(), seed=seed, dispatch_interval=60.0)
        c = engine_run(scen, CriticalPathDispatcher(), seed=seed, dispatch_interval=60.0)
        assert g.completed and c.completed
        greedy_makespans.append(g.makespan)
        cp_makespans.append(c.makespan)
    g_med = sorted(greedy_makespans)[len(seeds) // 2]
    c_med = sorted(cp_makespans)[len(seeds) // 2]
    assert c_med <= g_med + 1.0, f"critical_path regressed: greedy={g_med}, cp={c_med}"
