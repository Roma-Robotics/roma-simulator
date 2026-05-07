# roma-sim

Internal R&D simulator for Roma's autonomous-construction stack. The engine,
the scenario library, and the run database are the product. Live 3D, MQTT
bridges, streaming UIs, and the marketing-page integration all defer to later
weeks.

> **Optimize for**: an engineer can propose a new dispatcher policy on Monday
> and have a defensible answer by Friday.

## What's in this repo (Week 1)

- **Frozen, serializable domain types** — `Site`, `TaskGraph`, `Fleet`, `Event`,
  `World`, `Assignment`. No I/O, no behavior.
- **Dispatcher protocol** — the pluggable contract every policy implements.
  Stateless, deterministic, side-effect free.
- **Greedy nearest-task dispatcher** — the baseline every policy gets compared
  against.
- **SimPy-backed runner** — Tier 1.5: discrete events for durations, plus a 2D
  constant-speed travel model so spatial conflicts are observable.
- **Warehouse-shell scenario** — a tilt-up shell DAG (slab pour → cure →
  panel lift → install → finish) on a 100m × 60m site.
- **CLI** — `roma-sim run`.
- **Property tests** — DAG order respected, one-task-per-agent, monotonic
  event sequence, non-decreasing event time. Hypothesis-randomized over seeds.

Postgres + Parquet run store, multiprocess sweep runner, KPI module,
visual viewer, and the FastAPI/WebSocket bridge to the marketing page all
arrive in later weeks.

## Getting started

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

roma-sim run --seed 0
```

Each run lands in `runs/<timestamp>-<scenario>-<dispatcher>-s<seed>/`:
- `events.jsonl` — the durable artifact, one JSON event per line
- `metadata.json` — scenario / policy / seed / makespan / completion

## Architecture

Four core abstractions, defined in `src/roma_sim/domain/`:

```python
class Scenario(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def version(self) -> str: ...
    def build(self) -> tuple[Site, TaskGraph, Fleet]: ...

class Dispatcher(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def version(self) -> str: ...
    def assign(self, world: WorldView, ready: list[Task],
               idle: list[AgentState]) -> list[Assignment]: ...

@dataclass(frozen=True)
class World:
    t: float
    site: Site
    tasks: TaskGraph
    fleet: Fleet

@dataclass(frozen=True)
class Event:
    t: float
    seq: int
    kind: EventKind
    payload: Mapping[str, Any]
```

Everything else (SimPy, kinematics, sampling) is implementation detail behind
those four types.

### Determinism

Per-seed reproducibility, not bitwise determinism. All randomness flows through
a single `numpy.random.Generator` constructed from the run seed. The same
`(scenario_version, policy_version, seed)` triple produces the same event log,
verified by `tests/scenarios/test_warehouse_shell.py::test_run_is_seed_reproducible`.

## Testing

```bash
pytest                  # unit + property + scenario tests
ruff check src tests
mypy src
```
