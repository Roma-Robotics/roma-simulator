# roma-sim

Internal R&D simulator for Roma's autonomous-construction stack. The engine,
the scenario library, and the run database are the product. Live 3D, MQTT
bridges, streaming UIs, and the marketing-page integration all defer to later
weeks.

> **Optimize for**: an engineer can propose a new dispatcher policy on Monday
> and have a defensible answer by Friday.

## Status

- Pluggable `Dispatcher` Protocol with two implementations: `greedy` and
  `critical_path`. Engineers can drop in a new policy file and A/B test it
  against the rest in one CLI command.
- SimPy-backed engine with 2D constant-speed travel — Tier 1.5.
- Frozen, serializable domain types. Every run is fully described by
  `(scenario_version, policy_version, seed)` and produces an immutable event
  log that replays bit-for-bit on the same Python+NumPy build.
- Run store: SQLite metadata + Parquet event logs. Multiprocess sweep runner.
  `compare` aggregates KPI distributions across seeds.
- **Visual viewer**: `roma-sim play <run_id>` produces a self-contained
  `viewer.html` with timeline scrubber, play/pause, and 1×–3600× speed
  controls. Animates agents over the site with task states color-coded.
  No build step, no server, no fetch — just `file://` and a browser.
- 44 tests passing — domain, dispatcher units, scenario snapshots, KPI math,
  store roundtrip, sweep cells, replay timelines, viewer payload shape, and
  Hypothesis-randomized engine invariants.

Streamlit cross-run compare dashboard and the 2D collision-detection layer
arrive next.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

roma-sim --help                         # full CLI surface
roma-sim run --seed 0                   # one sim, persisted to ./runs/
roma-sim run --seed 0 --watch           # sim + open visual viewer in browser
```

## Visual viewer

```bash
roma-sim play <run_id>
# writes runs/runs/<run_id>/viewer.html and opens it in the browser
```

The viewer is a single self-contained HTML file: the run's payload (site
geometry, per-agent motion segments, per-task lifecycle timestamps, KPIs,
event log) is inlined as JSON and rendered on a Canvas2D stage with
keyboard shortcuts (Space = play/pause, ←/→ = scrub ±2 %, Home/End = jump).

It doubles as the contract for the eventual `Simulator.tsx` bridge to
roma's marketing site — same JSON shape, just a different renderer.

## The R&D loop

```bash
# 1. Hack on a new policy in src/roma_sim/dispatchers/<your_policy>.py.
#    Register it in src/roma_sim/dispatchers/__init__.py::_REGISTRY.

# 2. Sweep it against the baselines.
roma-sim sweep \
  --dispatchers greedy,critical_path,your_policy \
  --seeds 0:50 \
  --param panel_count=8,12,16 \
  --workers 8

# 3. Compare KPI distributions across seeds.
roma-sim compare --sweep <sweep_id>
```

Example output (`--seeds 0:10 --param panel_count=8,12`, two dispatchers):

```
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

40-cell sweep (2 dispatchers × 2 panel counts × 10 seeds) finishes in ~0.7s
wall time on 4 workers. The shell scenario itself is heavily gated by the
serial `cure → finish` path, so CP only beats greedy by ~0.2h here. Bring
your own scenario to find dispatcher gaps that matter.

## CLI surface

| command | what it does |
|---|---|
| `roma-sim run` | one simulation, persisted to the run store |
| `roma-sim sweep` | Cartesian product over `(dispatcher × param-grid × seeds)`, multiprocess |
| `roma-sim compare` | KPI table across a sweep or a list of run_ids |
| `roma-sim runs` | list recent runs |
| `roma-sim sweeps` | list recorded sweeps |
| `roma-sim show <run_id>` | show one run's metadata + KPIs |
| `roma-sim play <run_id>` | build self-contained HTML viewer + open in browser |
| `roma-sim list-dispatchers` / `list-scenarios` | registry inspection |

## Run store layout

```
runs/
├── index.sqlite          # one row per run, one row per sweep
└── runs/<run_id>/
    ├── events.parquet    # the durable event log
    └── metadata.json     # human-readable mirror
```

DuckDB reads SQLite + Parquet natively, so any ad-hoc analysis is a SQL query
away:

```python
import duckdb
con = duckdb.connect()
con.execute("INSTALL sqlite; LOAD sqlite;")
con.execute("ATTACH 'runs/index.sqlite' (TYPE SQLITE);")
con.sql("SELECT dispatcher_name, AVG(makespan_s)/3600 FROM index.runs GROUP BY 1").show()
con.sql("SELECT * FROM read_parquet('runs/runs/<run_id>/events.parquet')").show()
```

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Engine (pure Python, no IO)                                         │
│   Scenario  ──▶  World state  ──tick──▶  Dispatcher  ──▶  Events     │
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
                                               │  - notebooks (week3) │
                                               │  - Streamlit (week3) │
                                               └──────────────────────┘
```

The four core abstractions, defined in `src/roma_sim/domain/`:

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

## Determinism guarantees

Per-seed reproducibility, not bitwise determinism. All randomness flows
through one `numpy.random.Generator` constructed from the run seed. Two runs
with the same `(scenario_version, policy_version, seed)` produce identical
event logs, and the test suite pins this in
`tests/scenarios/test_warehouse_shell.py::test_run_is_seed_reproducible`.

The multiprocess sweep runner is deterministic per-cell: each worker re-seeds
its own RNG, so worker-pool scheduling order does not affect any individual
run's output.

## Repo layout

```
roma-simulator/
├── pyproject.toml
├── src/roma_sim/
│   ├── domain/                # frozen dataclasses, no IO
│   ├── engine/
│   │   ├── runner.py          # SimPy event loop
│   │   └── stochastics.py     # seeded duration sampling
│   ├── dispatchers/           # ← the R&D playground
│   │   ├── base.py            # Protocol
│   │   ├── greedy.py
│   │   └── critical_path.py
│   ├── scenarios/
│   │   └── warehouse_shell.py
│   ├── analysis/
│   │   └── kpis.py            # KPI computation from event logs
│   ├── runs/
│   │   ├── store.py           # SQLite + Parquet
│   │   ├── sweep.py           # multiprocess sweep runner
│   │   ├── compare.py         # KPI aggregation across runs
│   │   └── replay.py          # event log → viewer-ready timelines
│   ├── viewer/
│   │   ├── template.html      # self-contained Canvas2D player
│   │   └── builder.py         # bake payload into HTML, open browser
│   └── cli.py
└── tests/
    ├── property/              # Hypothesis tests on invariants
    ├── dispatchers/           # per-policy unit tests
    ├── scenarios/             # snapshot + reproducibility tests
    ├── test_kpis.py
    ├── test_store.py
    └── test_sweep.py
```

## Testing

```bash
pytest                       # 39 tests
ruff check src tests
mypy src
```

## Roadmap

- **Next**: Streamlit cross-run dashboard (KPI distributions across seeds
  per dispatcher), Hypothesis regression gates in CI, 2D spatial-conflict
  KPIs (`collisions_per_h`, `queue_depth_at_lift_bay`), FastAPI/WebSocket
  layer that streams a live run to the marketing `Simulator.tsx`.
- **Beyond**: ILP dispatcher with OR-Tools, parameterized scenarios from
  config, IFC ingestion, learned dispatcher trained on the event log.

## Defaults this scaffold picked

These were left open in the original plan — flagged here so they're easy to
revisit:

- **Hosting**: internal-only. SQLite + Parquet under `./runs/`. Hosted
  Postgres is a Week-4 task if we need it.
- **Determinism**: per-seed statistical reproducibility via
  `numpy.random.default_rng`. Bitwise cross-platform is not a goal at Tier 1.
- **Scenario authorship**: engineers-only Python. YAML / UI authoring deferred.
- **Existing tools**: schema is designed to be extensible to IFC / Revit / P6;
  Week 1 and 2 ship a synthetic warehouse shell.
