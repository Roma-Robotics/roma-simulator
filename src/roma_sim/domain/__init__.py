"""Frozen, serializable domain types. No I/O, no behavior."""

from __future__ import annotations

from roma_sim.domain.events import Event, EventKind
from roma_sim.domain.fleet import Agent, AgentState, Fleet
from roma_sim.domain.site import Site, Zone
from roma_sim.domain.tasks import Task, TaskGraph, TaskStatus
from roma_sim.domain.world import Assignment, World, WorldView

__all__ = [
    "Agent",
    "AgentState",
    "Assignment",
    "Event",
    "EventKind",
    "Fleet",
    "Site",
    "Task",
    "TaskGraph",
    "TaskStatus",
    "World",
    "WorldView",
    "Zone",
]
