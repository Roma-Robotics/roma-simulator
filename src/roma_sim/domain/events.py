"""Events are the only persistent output of a run.

A run is fully described by `(scenario_version, policy_version, seed, [Event...])`.
Replaying that event log must reproduce every World snapshot at every tick.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventKind(str, Enum):
    SIM_START = "sim_start"
    SIM_END = "sim_end"
    TICK = "tick"
    TASK_READY = "task_ready"
    TASK_ASSIGNED = "task_assigned"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    AGENT_MOVE_START = "agent_move_start"
    AGENT_MOVE_END = "agent_move_end"
    AGENT_IDLE = "agent_idle"
    AGENT_BUSY = "agent_busy"


@dataclass(frozen=True)
class Event:
    """A timestamped, ordered, immutable observation of the simulated world.

    Attributes:
        t:        simulation time in seconds.
        seq:     monotonically increasing sequence number; ties break ordering at equal `t`.
        kind:    discriminator for `payload`.
        payload: JSON-serializable mapping. Only primitives, lists, dicts.
    """

    t: float
    seq: int
    kind: EventKind
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "t": self.t,
            "seq": self.seq,
            "kind": self.kind.value,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_json(cls, obj: Mapping[str, Any]) -> Event:
        return cls(
            t=float(obj["t"]),
            seq=int(obj["seq"]),
            kind=EventKind(obj["kind"]),
            payload=dict(obj.get("payload", {})),
        )
