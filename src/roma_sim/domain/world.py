"""World snapshot and the read-only view passed to dispatchers.

`World` is the canonical immutable state. `WorldView` is a thin alias today
(same object) but exists as a distinct type so we can later strip mutating
methods or substitute an indexed view without changing dispatcher signatures.

`Assignment` is the only thing a dispatcher returns: "agent A takes task T".
"""

from __future__ import annotations

from dataclasses import dataclass

from roma_sim.domain.fleet import Fleet
from roma_sim.domain.site import Site
from roma_sim.domain.tasks import TaskGraph


@dataclass(frozen=True)
class World:
    t: float
    site: Site
    tasks: TaskGraph
    fleet: Fleet

    @property
    def is_done(self) -> bool:
        return self.tasks.is_done()


# A WorldView is intentionally identical to World today. Dispatchers must treat
# it as read-only. Keeping the alias gives us a seam to enforce that later.
WorldView = World


@dataclass(frozen=True)
class Assignment:
    """A dispatcher's decision: assign `task_id` to `agent_id` at time `t`."""

    agent_id: str
    task_id: str

    def __post_init__(self) -> None:
        if not self.agent_id:
            raise ValueError("Assignment.agent_id must be non-empty")
        if not self.task_id:
            raise ValueError("Assignment.task_id must be non-empty")
