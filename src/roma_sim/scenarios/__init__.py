"""Scenarios: parameterized world + work generators."""

from __future__ import annotations

from roma_sim.engine.runner import Scenario
from roma_sim.scenarios.warehouse_shell import WarehouseShellScenario

__all__ = ["Scenario", "WarehouseShellScenario", "get_scenario"]


def get_scenario(name: str, **params: object) -> Scenario:
    """Resolve a scenario by short name."""
    registry = {
        "warehouse_shell": WarehouseShellScenario,
    }
    if name not in registry:
        raise KeyError(f"unknown scenario {name!r}; available: {sorted(registry)}")
    return registry[name](**params)  # type: ignore[arg-type]
