"""Tests for replay timelines and viewer payload assembly."""

from __future__ import annotations

import json

from roma_sim.dispatchers.greedy import GreedyNearestDispatcher
from roma_sim.engine import run as engine_run
from roma_sim.runs.replay import (
    build_agent_timelines,
    build_task_timelines,
    build_viewer_payload,
)
from roma_sim.scenarios.warehouse_shell import WarehouseShellScenario
from roma_sim.viewer.builder import build_viewer_html


def _do_run():
    scen = WarehouseShellScenario(panel_count=4)
    return scen, engine_run(scen, GreedyNearestDispatcher(), seed=0, dispatch_interval=60.0)


def test_agent_timelines_have_monotonic_moves() -> None:
    scen, result = _do_run()
    timelines = build_agent_timelines(result.events, result.final_world.fleet)
    assert set(timelines) == {a.id for a in result.final_world.fleet.agents}
    for tl in timelines.values():
        for prev, cur in zip(tl.moves, tl.moves[1:]):
            assert prev.t0 <= cur.t0
            assert prev.t1 <= cur.t1
            assert cur.t0 >= prev.t1 - 1e-6


def test_agent_work_intervals_close_at_completion() -> None:
    scen, result = _do_run()
    timelines = build_agent_timelines(result.events, result.final_world.fleet)
    # Every work interval must be (t0 < t1) and reference a known task id.
    for tl in timelines.values():
        for w in tl.work:
            assert w["t1"] >= w["t0"]
            assert isinstance(w["task_id"], str) and w["task_id"]


def test_task_timelines_capture_lifecycle() -> None:
    scen, result = _do_run()
    site, initial_tasks, _ = scen.build()
    timelines = build_task_timelines(result.events, initial_tasks.tasks)
    for tl in timelines.values():
        # Every task that completed must have ready < started < completed.
        if tl.completed_at is not None:
            assert tl.started_at is not None
            assert tl.ready_at is not None
            assert tl.ready_at <= tl.started_at <= tl.completed_at
            assert tl.assigned_to is not None


def test_viewer_payload_is_json_serializable() -> None:
    scen, result = _do_run()
    site, initial_tasks, fleet = scen.build()
    payload = build_viewer_payload(
        result.events,
        site,
        result.final_world.fleet,
        initial_tasks.tasks,
        run_id="rid-test",
        scenario_name=result.scenario_name,
        scenario_version=result.scenario_version,
        dispatcher_name=result.dispatcher_name,
        dispatcher_version=result.dispatcher_version,
        seed=result.seed,
    )
    blob = json.dumps(payload)
    assert "rid-test" in blob
    assert payload["site"]["name"] == site.name
    assert len(payload["agents"]) == len(fleet.agents)
    assert len(payload["tasks"]) == len(initial_tasks.tasks)
    assert payload["makespan_s"] > 0


def test_viewer_html_inlines_payload() -> None:
    scen, result = _do_run()
    site, initial_tasks, fleet = scen.build()
    payload = build_viewer_payload(
        result.events,
        site,
        result.final_world.fleet,
        initial_tasks.tasks,
        run_id="rid-html",
        scenario_name=result.scenario_name,
        scenario_version=result.scenario_version,
        dispatcher_name=result.dispatcher_name,
        dispatcher_version=result.dispatcher_version,
        seed=result.seed,
    )
    html = build_viewer_html(payload)
    assert "<canvas" in html
    assert "rid-html" in html
    assert "__RUN_DATA__" not in html  # placeholder must be replaced
    assert "__RUN_TITLE__" not in html
    # No raw `</script>` slipped through inside the payload.
    body = html.split('id="run-data"', 1)[1]
    body = body.split("</script>", 1)[0]
    assert "</script>" not in body
