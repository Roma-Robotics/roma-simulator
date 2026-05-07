# roma-sim

Deterministic multi-agent construction simulator for Roma’s autonomous-construction stack.

`roma-sim` is an internal R&D platform for testing dispatch and coordination
policies across simulated construction fleets. It provides reproducible runs,
parameter sweeps, KPI comparison tooling, and a browser-based replay viewer
for analyzing agent behavior over time.

---

## Features

- Deterministic SimPy-based simulation engine
- Pluggable dispatcher policies (`greedy`, `critical_path`, custom policies)
- Multiprocess parameter sweeps with KPI comparison tooling
- Immutable event-log replay system backed by SQLite + Parquet
- Self-contained browser viewer with timeline playback and agent animation
- Fully typed, frozen domain model with reproducible seeded runs
- 44-test suite covering engine invariants, replay integrity, KPI math,
  store roundtrips, and randomized property tests

---

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

roma-sim --help
roma-sim run --seed 0
roma-sim run --seed 0 --watch
```

---

## Visual viewer

```bash
roma-sim play <run_id>
```

Builds a fully self-contained `viewer.html` and opens it in the browser.

The viewer includes:

- timeline scrubber
- play / pause controls
- 1×–3600× playback speed
- agent motion playback
- task lifecycle visualization
- keyboard shortcuts
- embedded event-log payload

No build step, server, or fetch requests required — just `file://` and a
browser.

The replay payload doubles as the contract for the eventual
`Simulator.tsx` bridge powering Roma’s marketing site.

---

## The R&D loop

```bash
# 1. Create a new dispatcher policy.
#    src/roma_sim/dispatchers/<your_policy>.py

# 2. Register it.
#    src/roma_sim/dispatchers/__init__.py::_REGISTRY

# 3. Sweep against baselines.
roma-sim sweep \
  --dispatchers greedy,critical_path,your_policy \
  --seeds 0:50 \
  --param panel_count=8,12,16 \
  --workers 8

# 4. Compare KPI distributions.
roma-sim compare --sweep <sweep_id>
```

Example output:

```text
              compare sweep=327da9c0b0f4
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━┳━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┓
┃ dispatcher    ┃ params         ┃  n ┃ done ┃ makespan_p50 ┃ makespan_p95 ┃ crew_idle_% ┃ tasks/h ┃ cycle_p50 ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━╇━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━┩
│ critical_path │ panel_count=12 │ 10 │   10 │       22.12h │       22.98h │       75.5% │    1.26 │     57.2m │
│ greedy        │ panel_count=12 │ 10 │   10 │       22.41h │       23.19h │       76.0% │    1.25 │     54.0m │
│ critical_path │ panel_count=8  │ 10 │   10 │       21.34h │       21.96h │       77.0% │    0.94 │     56.1m │
│ greedy        │ panel_count=8  │ 10 │   10 │       21.50h │       22.19h │       77.3% │    0.94 │     53.2m │
└───────────────┴────────────────┴────┴──────┴──────────────┴──────────────┴─────────────┴─────────┴───────────┘
```

A 40-cell sweep (2 dispatchers × 2 panel counts × 10 seeds) finishes in
~0.7s wall time on 4 workers.

---

## CLI surface

| command | description |
|---|---|
| `roma-sim run` | run one simulation |
| `roma-sim sweep` | Cartesian sweep across dispatchers, params, and seeds |
| `roma-sim compare` | aggregate KPI distributions |
| `roma-sim runs` | list recent runs |
| `roma-sim sweeps` | list recorded sweeps |
| `roma-sim show <run_id>` | inspect metadata + KPIs |
| `roma-sim play <run_id>` | build replay viewer |
| `roma-sim list-dispatchers` | inspect dispatcher registry |
| `roma-sim list-scenarios` | inspect scenario registry |

---

## Run store layout

```text
runs/
├── index.sqlite
└── runs/<run_id>/
    ├── events.parquet
    └── metadata.json
```

Each run is fully described by:

```text
(scenario_version, policy_version, seed)
```

Runs are immutable and replayable on the same Python + NumPy build.

DuckDB can query SQLite and Parquet directly:

```python
import duckdb

con = duckdb.connect()

con.execute("INSTALL sqlite; LOAD sqlite;")
con.execute("ATTACH 'runs/index.sqlite' (TYPE SQLITE);")

con.sql("""
SELECT dispatcher_name,
       AVG(makespan_s)/3600
FROM index.runs
GROUP BY 1
""").show()

con.sql("""
SELECT *
FROM read_parquet('runs/runs/<run_id>/events.parquet')
""").show()
```

---

## Architecture

```text
┌──────────────────────────────────────────────────────────────────────┐
│  Engine (pure Python, no IO)                                        │
│                                                                      │
│   Scenario ──▶ World state ──tick──▶ Dispatcher ──▶ Events           │
└──────────────────────────────────────────────────────────────────────┘
            │                                              │
            ▼                                              ▼
┌─────────────────────┐                       ┌──────────────────────┐
│  CLI / Notebook     │                       │  Run store           │
│  - run one          │                       │  - SQLite metadata   │
│  - sweep N runs     │                       │  - Parquet event log │
│  - compare          │                       │  - DuckDB-queryable  │
└─────────────────────┘                       └──────────────────────┘
                                                         │
                                                         ▼
                                               ┌──────────────────────┐
                                               │  Compare / Analyze   │
                                               │  - KPI module        │
                                               │  - notebooks         │
                                               │  - Streamlit         │
                                               └──────────────────────┘
```

Core abstractions:

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

    def assign(
        self,
        world: WorldView,
        ready: list[Task],
        idle: list[AgentState],
    ) -> list[Assignment]: ...


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

---

## Determinism guarantees

All stochastic behavior flows through a single seeded
`numpy.random.Generator`.

Two runs with the same:

```text
(scenario_version, policy_version, seed)
```

produce identical event logs on the same Python + NumPy build.

Multiprocess sweeps remain deterministic per-cell because each worker
re-seeds its own RNG independently.

Seed reproducibility is pinned in:

```text
tests/scenarios/test_warehouse_shell.py::test_run_is_seed_reproducible
```

Bitwise cross-platform determinism is not currently a goal.

---

## Repo layout

```text
roma-simulator/
├── pyproject.toml
├── src/roma_sim/
│   ├── domain/
│   ├── engine/
│   │   ├── runner.py
│   │   └── stochastics.py
│   ├── dispatchers/
│   │   ├── base.py
│   │   ├── greedy.py
│   │   └── critical_path.py
│   ├── scenarios/
│   │   └── warehouse_shell.py
│   ├── analysis/
│   │   └── kpis.py
│   ├── runs/
│   │   ├── store.py
│   │   ├── sweep.py
│   │   ├── compare.py
│   │   └── replay.py
│   ├── viewer/
│   │   ├── template.html
│   │   └── builder.py
│   └── cli.py
└── tests/
    ├── property/
    ├── dispatchers/
    ├── scenarios/
    ├── test_kpis.py
    ├── test_store.py
    └── test_sweep.py
```

---

## Testing

```bash
pytest
ruff check src tests
mypy src
```

Current coverage includes:

- dispatcher policy tests
- scenario snapshots
- KPI validation
- store roundtrips
- replay payload integrity
- Hypothesis property tests
- engine invariant checks

---

## Roadmap

### Next

- Streamlit cross-run KPI dashboard
- Hypothesis regression gates in CI
- 2D spatial-conflict KPIs
  - `collisions_per_h`
  - `queue_depth_at_lift_bay`
- FastAPI/WebSocket live-run streaming
- `Simulator.tsx` bridge for Roma marketing demos

### Beyond

- OR-Tools ILP dispatcher
- parameterized config-driven scenarios
- IFC ingestion
- learned dispatch policies trained from event logs

---

## Defaults and tradeoffs

These choices were intentionally optimized for iteration speed at Tier 1:

| area | decision |
|---|---|
| hosting | local SQLite + Parquet |
| determinism | seeded reproducibility |
| scenario authoring | Python-only |
| deployment target | internal R&D |
| geometry | synthetic warehouse shell |
| persistence | immutable event logs |

The schema is intentionally extensible toward:

- IFC / Revit ingestion
- Primavera / P6 schedule integration
- live fleet telemetry
- distributed simulation execution
- browser-native visualization
