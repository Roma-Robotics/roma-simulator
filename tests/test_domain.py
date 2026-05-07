"""Domain-type sanity tests."""

from __future__ import annotations

import pytest

from roma_sim.domain import (
    Event,
    EventKind,
    Site,
    Task,
    TaskGraph,
    TaskStatus,
    Zone,
)


def test_zone_centroid_matches_geometry() -> None:
    z = Zone(id="z", name="Z", x=10.0, y=20.0, width=10.0, height=20.0)
    assert z.centroid == (15.0, 30.0)


def test_site_rejects_duplicate_zone_ids() -> None:
    with pytest.raises(ValueError):
        Site(
            name="x",
            width=1,
            height=1,
            zones=(
                Zone(id="a", name="A", x=0, y=0, width=1, height=1),
                Zone(id="a", name="A2", x=0, y=0, width=1, height=1),
            ),
        )


def test_taskgraph_rejects_unknown_dep() -> None:
    with pytest.raises(ValueError):
        TaskGraph(
            tasks=(
                Task(
                    id="t",
                    name="t",
                    skill="x",
                    zone_id="z",
                    duration_mean=1.0,
                    duration_std=0.0,
                    deps=("missing",),
                ),
            )
        )


def test_taskgraph_rejects_cycles() -> None:
    with pytest.raises(ValueError):
        TaskGraph(
            tasks=(
                Task(
                    id="a",
                    name="a",
                    skill="x",
                    zone_id="z",
                    duration_mean=1.0,
                    duration_std=0.0,
                    deps=("b",),
                ),
                Task(
                    id="b",
                    name="b",
                    skill="x",
                    zone_id="z",
                    duration_mean=1.0,
                    duration_std=0.0,
                    deps=("a",),
                ),
            )
        )


def test_mark_ready_promotes_zero_dep_tasks() -> None:
    tg = TaskGraph(
        tasks=(
            Task(
                id="a",
                name="a",
                skill="x",
                zone_id="z",
                duration_mean=1.0,
                duration_std=0.0,
                deps=(),
            ),
            Task(
                id="b",
                name="b",
                skill="x",
                zone_id="z",
                duration_mean=1.0,
                duration_std=0.0,
                deps=("a",),
            ),
        )
    )
    tg2 = tg.mark_ready()
    assert tg2.by_id("a").status is TaskStatus.READY
    assert tg2.by_id("b").status is TaskStatus.PENDING


def test_event_roundtrip_json() -> None:
    e = Event(t=12.5, seq=3, kind=EventKind.TASK_COMPLETED, payload={"task_id": "t"})
    assert Event.from_json(e.to_json()) == e
