"""Unit tests for GreedyNearestDispatcher.

These tests run against synthetic WorldViews -- no engine, no SimPy, no time.
Pure function tests, the kind we want a Roma engineer to write a hundred of.
"""

from __future__ import annotations

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


def _site() -> Site:
    return Site(
        name="test",
        width=100.0,
        height=100.0,
        zones=(
            Zone(id="a", name="A", x=0.0, y=0.0, width=10.0, height=10.0),
            Zone(id="b", name="B", x=80.0, y=80.0, width=10.0, height=10.0),
        ),
    )


def _agent(aid: str, x: float, y: float, skills=("pour",)) -> AgentState:
    return AgentState(
        agent=Agent(
            id=aid,
            name=aid,
            skills=frozenset(skills),
            speed_mps=1.0,
            home_x=x,
            home_y=y,
        ),
        x=x,
        y=y,
    )


def _task(tid: str, zone: str, skill: str = "pour") -> Task:
    return Task(
        id=tid,
        name=tid,
        skill=skill,
        zone_id=zone,
        duration_mean=60.0,
        duration_std=0.0,
        deps=(),
        status=TaskStatus.READY,
    )


def _world(tasks, agents) -> World:
    return World(
        t=0.0,
        site=_site(),
        tasks=TaskGraph(tasks=tuple(tasks)),
        fleet=Fleet(agents=tuple(agents)),
    )


def test_assigns_each_idle_agent_to_nearest_compatible_task() -> None:
    a1 = _agent("a1", 0.0, 0.0)
    a2 = _agent("a2", 90.0, 90.0)
    t_near_a1 = _task("t_near_a1", "a")
    t_near_a2 = _task("t_near_a2", "b")
    world = _world([t_near_a1, t_near_a2], [a1, a2])

    out = GreedyNearestDispatcher().assign(world, [t_near_a1, t_near_a2], [a1, a2])

    pairs = {(x.agent_id, x.task_id) for x in out}
    assert pairs == {("a1", "t_near_a1"), ("a2", "t_near_a2")}


def test_skips_tasks_agent_cant_perform() -> None:
    a1 = _agent("a1", 0.0, 0.0, skills=("pour",))
    t_lift = _task("t_lift", "a", skill="lift")
    world = _world([t_lift], [a1])

    out = GreedyNearestDispatcher().assign(world, [t_lift], [a1])
    assert out == []


def test_no_double_assignment_of_task() -> None:
    a1 = _agent("a1", 0.0, 0.0)
    a2 = _agent("a2", 1.0, 1.0)
    t = _task("t", "a")
    world = _world([t], [a1, a2])

    out = GreedyNearestDispatcher().assign(world, [t], [a1, a2])
    assert len(out) == 1
    assert out[0].task_id == "t"


def test_deterministic_with_ties() -> None:
    a1 = _agent("a1", 50.0, 50.0)
    t1 = _task("t1", "a")
    t2 = _task("t2", "b")
    world = _world([t1, t2], [a1])

    out1 = GreedyNearestDispatcher().assign(world, [t1, t2], [a1])
    out2 = GreedyNearestDispatcher().assign(world, [t2, t1], [a1])
    assert out1 == out2


def test_no_assignments_when_no_idle_agents() -> None:
    t = _task("t", "a")
    world = _world([t], [])
    assert GreedyNearestDispatcher().assign(world, [t], []) == []


def test_no_assignments_when_no_ready_tasks() -> None:
    a = _agent("a1", 0.0, 0.0)
    world = _world([], [a])
    assert GreedyNearestDispatcher().assign(world, [], [a]) == []
