"""Fleet: agents and their kinematic state.

`Agent` is the immutable nameplate (skills, speed, home position). `AgentState`
is the per-tick position + busy bit. `Fleet` is a collection of `AgentState`s.

Skills are strings (e.g. `"pour"`, `"lift"`, `"install"`). An agent can perform
any task whose `skill` is in `agent.skills`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Agent:
    id: str
    name: str
    skills: frozenset[str]
    speed_mps: float  # meters per second
    home_x: float
    home_y: float


@dataclass(frozen=True)
class AgentState:
    agent: Agent
    x: float
    y: float
    busy: bool = False
    current_task: str | None = None

    @property
    def id(self) -> str:
        return self.agent.id

    @property
    def position(self) -> tuple[float, float]:
        return (self.x, self.y)

    def can_perform(self, skill: str) -> bool:
        return skill in self.agent.skills


@dataclass(frozen=True)
class Fleet:
    agents: tuple[AgentState, ...]

    def __post_init__(self) -> None:
        ids = [a.id for a in self.agents]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate agent ids: {ids}")

    def by_id(self, agent_id: str) -> AgentState:
        for a in self.agents:
            if a.id == agent_id:
                return a
        raise KeyError(f"unknown agent {agent_id!r}")

    def idle(self) -> list[AgentState]:
        return [a for a in self.agents if not a.busy]

    def busy(self) -> list[AgentState]:
        return [a for a in self.agents if a.busy]

    def replace_agent(self, agent_state: AgentState) -> Fleet:
        new_agents = tuple(
            agent_state if a.id == agent_state.id else a for a in self.agents
        )
        return Fleet(agents=new_agents)

    def replace_agents(self, updates: Iterable[AgentState]) -> Fleet:
        index = {a.id: a for a in updates}
        new_agents = tuple(index.get(a.id, a) for a in self.agents)
        return Fleet(agents=new_agents)

    def with_position(self, agent_id: str, x: float, y: float) -> Fleet:
        a = self.by_id(agent_id)
        return self.replace_agent(replace(a, x=x, y=y))

    def with_busy(
        self, agent_id: str, busy: bool, current_task: str | None = None
    ) -> Fleet:
        a = self.by_id(agent_id)
        return self.replace_agent(replace(a, busy=busy, current_task=current_task))
