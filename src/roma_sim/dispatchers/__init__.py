"""Dispatcher policies — the R&D playground.

Every policy implements `Dispatcher`. They are stateless and deterministic:
same `(world, ready, idle)` -> same assignments. That property is what makes
A/B comparisons across seeds meaningful.
"""

from __future__ import annotations

from roma_sim.dispatchers.base import Dispatcher
from roma_sim.dispatchers.critical_path import CriticalPathDispatcher
from roma_sim.dispatchers.greedy import GreedyNearestDispatcher

__all__ = [
    "CriticalPathDispatcher",
    "Dispatcher",
    "GreedyNearestDispatcher",
    "available_dispatchers",
    "get_dispatcher",
]


_REGISTRY: dict[str, Dispatcher] = {
    "greedy": GreedyNearestDispatcher(),
    "critical_path": CriticalPathDispatcher(),
}


def get_dispatcher(name: str) -> Dispatcher:
    """Resolve a dispatcher by short name. Used by the CLI."""
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown dispatcher {name!r}; available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]


def available_dispatchers() -> list[Dispatcher]:
    return list(_REGISTRY.values())
