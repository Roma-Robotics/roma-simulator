"""The dispatcher contract.

This is the most important file in the repo. Dispatchers are pluggable code;
the engine's job is to feed them snapshots and execute their decisions.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from roma_sim.domain import AgentState, Assignment, Task, WorldView


@runtime_checkable
class Dispatcher(Protocol):
    """Pure assignment policy.

    Implementations MUST be:
      * Stateless across calls (any internal state is a cache, not memory).
      * Deterministic: equal inputs produce equal outputs (modulo set ordering
        we explicitly normalize). The engine seeds any randomness it owns.
      * Side-effect free: never mutate `world`, `ready`, or `idle`.
    """

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def assign(
        self,
        world: WorldView,
        ready: list[Task],
        idle: list[AgentState],
    ) -> list[Assignment]:
        """Return a list of (agent, task) pairings to execute now.

        Constraints the engine validates:
          * No agent appears in more than one returned `Assignment`.
          * No task appears in more than one returned `Assignment`.
          * Every assigned task is in `ready`; every assigned agent is in `idle`.
          * The agent's skill set must include the task's required skill.

        Invalid assignments are dropped by the engine and logged as a warning.
        """
        ...
