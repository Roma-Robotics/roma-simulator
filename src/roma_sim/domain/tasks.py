"""Tasks and the task graph.

A `Task` is a unit of work the dispatcher can assign to an agent with the
matching skill. `TaskGraph` enforces DAG semantics: a task is `READY` only when
every dependency has been `COMPLETED`.

The graph itself is frozen; status transitions produce a new graph via
`with_status`. This keeps every snapshot a value, never a mutable handle.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"  # blocked by deps
    READY = "ready"  # dispatchable
    IN_PROGRESS = "in_progress"  # assigned and being executed
    COMPLETED = "completed"


@dataclass(frozen=True)
class Task:
    """A single unit of work.

    Attributes:
        id:            unique within a TaskGraph.
        name:          human-readable label.
        skill:         skill required of the agent that executes it.
        zone_id:       zone where the work is performed (drives travel cost).
        duration_mean: mean nominal duration in seconds.
        duration_std:  std-dev for stochastic sampling (0 = deterministic).
        deps:          ids of tasks that must be COMPLETED before this is READY.
        status:        current lifecycle state.
        assigned_to:   agent id once assigned, else None.
    """

    id: str
    name: str
    skill: str
    zone_id: str
    duration_mean: float
    duration_std: float
    deps: tuple[str, ...]
    status: TaskStatus = TaskStatus.PENDING
    assigned_to: str | None = None


@dataclass(frozen=True)
class TaskGraph:
    tasks: tuple[Task, ...]

    def __post_init__(self) -> None:
        ids = [t.id for t in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate task ids: {ids}")
        idset = set(ids)
        for t in self.tasks:
            unknown = [d for d in t.deps if d not in idset]
            if unknown:
                raise ValueError(f"task {t.id!r} references unknown deps: {unknown}")
        # Kahn's algorithm: topo-sort to confirm acyclic.
        indeg = {t.id: len(t.deps) for t in self.tasks}
        children: dict[str, list[str]] = {tid: [] for tid in ids}
        for t in self.tasks:
            for d in t.deps:
                children[d].append(t.id)
        queue = [tid for tid, c in indeg.items() if c == 0]
        seen = 0
        while queue:
            n = queue.pop()
            seen += 1
            for c in children[n]:
                indeg[c] -= 1
                if indeg[c] == 0:
                    queue.append(c)
        if seen != len(self.tasks):
            raise ValueError("task graph contains a cycle")

    def by_id(self, task_id: str) -> Task:
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise KeyError(f"unknown task {task_id!r}")

    def replace_task(self, task: Task) -> TaskGraph:
        new_tasks = tuple(task if t.id == task.id else t for t in self.tasks)
        return TaskGraph(tasks=new_tasks)

    def replace_tasks(self, updates: Iterable[Task]) -> TaskGraph:
        index = {t.id: t for t in updates}
        new_tasks = tuple(index.get(t.id, t) for t in self.tasks)
        return TaskGraph(tasks=new_tasks)

    def ready(self) -> list[Task]:
        return [t for t in self.tasks if t.status is TaskStatus.READY]

    def pending(self) -> list[Task]:
        return [t for t in self.tasks if t.status is TaskStatus.PENDING]

    def in_progress(self) -> list[Task]:
        return [t for t in self.tasks if t.status is TaskStatus.IN_PROGRESS]

    def completed(self) -> list[Task]:
        return [t for t in self.tasks if t.status is TaskStatus.COMPLETED]

    def is_done(self) -> bool:
        return all(t.status is TaskStatus.COMPLETED for t in self.tasks)

    def deps_satisfied(self, task: Task) -> bool:
        completed_ids = {t.id for t in self.tasks if t.status is TaskStatus.COMPLETED}
        return all(d in completed_ids for d in task.deps)

    def newly_ready(self) -> list[Task]:
        """PENDING tasks whose deps are now satisfied."""
        return [
            t
            for t in self.tasks
            if t.status is TaskStatus.PENDING and self.deps_satisfied(t)
        ]

    def mark_ready(self) -> TaskGraph:
        """Promote all eligible PENDING tasks to READY."""
        promote = self.newly_ready()
        if not promote:
            return self
        return self.replace_tasks(replace(t, status=TaskStatus.READY) for t in promote)
