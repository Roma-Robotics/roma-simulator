"""Dispatcher policies — the R&D playground.

Every policy implements `Dispatcher`. They are stateless and deterministic:
same `(world, ready, idle)` -> same assignments. That property is what makes
A/B comparisons across seeds meaningful.
"""

from __future__ import annotations

from roma_sim.dispatchers.base import Dispatcher
from roma_sim.dispatchers.greedy import GreedyNearestDispatcher

__all__ = ["Dispatcher", "GreedyNearestDispatcher", "get_dispatcher"]


def get_dispatcher(name: str) -> Dispatcher:
    """Resolve a dispatcher by short name. Used by the CLI."""
    registry: dict[str, Dispatcher] = {
        "greedy": GreedyNearestDispatcher(),
    }
    if name not in registry:
        raise KeyError(
            f"unknown dispatcher {name!r}; available: {sorted(registry)}"
        )
    return registry[name]
