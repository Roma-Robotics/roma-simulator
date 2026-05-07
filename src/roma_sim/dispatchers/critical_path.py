"""Critical-path dispatcher.

For each ready task, computes the longest *remaining* path in the DAG
weighted by `duration_mean`. Ready tasks on the longest path win the next
available agent. Agents are still picked by nearest-zone among compatible
candidates.

This is the textbook scheduler from project-management theory; it's a strong
baseline for any DAG where one slow successor (the `finish` task in our shell
scenario) gates everything else.
"""

from __future__ import annotations

from dataclasses import dataclass

from roma_sim.domain import (
    AgentState,
    Assignment,
    Task,
    TaskGraph,
    TaskStatus,
    WorldView,
)
from roma_sim.domain.site import euclidean


@dataclass(frozen=True)
class CriticalPathDispatcher:
    name: str = "critical_path"
    version: str = "0.1.0"

    def assign(
        self,
        world: WorldView,
        ready: list[Task],
        idle: list[AgentState],
    ) -> list[Assignment]:
        priority = _longest_remaining_path(world.tasks)

        # Highest CP priority first; tie-break on task id for determinism.
        sorted_tasks = sorted(ready, key=lambda t: (-priority.get(t.id, 0.0), t.id))
        remaining_agents = sorted(idle, key=lambda a: a.id)

        assignments: list[Assignment] = []
        for task in sorted_tasks:
            best: AgentState | None = None
            best_d = float("inf")
            for agent in remaining_agents:
                if not agent.can_perform(task.skill):
                    continue
                zone = world.site.zone(task.zone_id)
                d = euclidean(agent.position, zone.centroid)
                if d < best_d or (d == best_d and best is not None and agent.id < best.id):
                    best = agent
                    best_d = d
            if best is not None:
                assignments.append(Assignment(agent_id=best.id, task_id=task.id))
                remaining_agents = [a for a in remaining_agents if a.id != best.id]

        return assignments


def _longest_remaining_path(graph: TaskGraph) -> dict[str, float]:
    """Length of the longest path from each task to any leaf, by mean duration.

    Completed tasks contribute zero. The dictionary always contains every task
    id in the graph.
    """
    children: dict[str, list[str]] = {t.id: [] for t in graph.tasks}
    for t in graph.tasks:
        for d in t.deps:
            children.setdefault(d, []).append(t.id)

    cache: dict[str, float] = {}
    in_progress: set[str] = set()  # cycle guard; TaskGraph already validates DAG.

    def visit(tid: str) -> float:
        if tid in cache:
            return cache[tid]
        if tid in in_progress:
            return 0.0
        in_progress.add(tid)
        task = graph.by_id(tid)
        own = 0.0 if task.status is TaskStatus.COMPLETED else task.duration_mean
        downstream = max((visit(c) for c in children.get(tid, [])), default=0.0)
        result = own + downstream
        in_progress.remove(tid)
        cache[tid] = result
        return result

    return {t.id: visit(t.id) for t in graph.tasks}
