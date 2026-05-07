"""Greedy nearest-task dispatcher.

For each idle agent, choose the unclaimed ready task whose zone centroid is
closest to the agent, subject to skill match. Iterates agents in id order so
ties break deterministically across seeds.

This is the baseline every other policy gets compared against.
"""

from __future__ import annotations

from dataclasses import dataclass

from roma_sim.domain import AgentState, Assignment, Task, WorldView
from roma_sim.domain.site import euclidean


@dataclass(frozen=True)
class GreedyNearestDispatcher:
    name: str = "greedy"
    version: str = "0.1.0"

    def assign(
        self,
        world: WorldView,
        ready: list[Task],
        idle: list[AgentState],
    ) -> list[Assignment]:
        assignments: list[Assignment] = []
        # Mutable working copies, sorted for determinism.
        remaining_tasks = sorted(ready, key=lambda t: t.id)
        remaining_agents = sorted(idle, key=lambda a: a.id)

        for agent in remaining_agents:
            best: Task | None = None
            best_d = float("inf")
            for task in remaining_tasks:
                if not agent.can_perform(task.skill):
                    continue
                zone = world.site.zone(task.zone_id)
                d = euclidean(agent.position, zone.centroid)
                # Lexicographic tiebreak on task.id for determinism.
                if d < best_d or (d == best_d and best is not None and task.id < best.id):
                    best = task
                    best_d = d
            if best is not None:
                assignments.append(Assignment(agent_id=agent.id, task_id=best.id))
                remaining_tasks = [t for t in remaining_tasks if t.id != best.id]

        return assignments
