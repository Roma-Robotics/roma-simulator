# roma-sim

Internal R&D simulator for Roma's autonomous-construction stack. The engine,
the scenario library, and the run database are the product. Live 3D, MQTT
bridges, streaming UIs, and the marketing-page integration all defer to later
weeks.

> **Optimize for**: an engineer can propose a new dispatcher policy on Monday
> and have a defensible answer by Friday.

## Status (end of Week 2)

- Pluggable `Dispatcher` Protocol with two implementations: `greedy` and
  `critical_path`. Engineers can drop in a new policy file and A/B test it
  against the rest in one CLI command.
- SimPy-backed engine with 2D constant-speed travel — Tier 1.5.
- Frozen, serializable domain types. Every run is fully described by
  `(scenario_version, policy_version, seed)` and produces an immutable event
  log that replays bit-for-bit on the same Python+NumPy build.
- Run store: SQLite metadata + Parquet event logs. Multiprocess sweep runner.
  `compare` aggregates KPI distributions across seeds.
- 39 tests passing — domain, dispatcher units, scenario snapshots, KPI math,
  store roundtrip, sweep cells, and Hypothesis-randomized engine invariants.

Replay (event-log → frame-by-frame `World[]`) and a visual viewer arrive in
Week 3.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

roma-sim --help                         # full CLI surface
roma-sim run --seed 0                   # one sim, persisted to ./runs/
```

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

## CLI surface

| command | what it does |
|---|---|
| `roma-sim run` | one simulation, persisted to the run store |
| `roma-sim sweep` | Cartesian product over `(dispatcher × param-grid × seeds)`, multiprocess |
| `roma-sim compare` | KPI table across a sweep or a list of run_ids |
| `roma-sim runs` | list recent runs |
| `roma-sim sweeps` | list recorded sweeps |
| `roma-sim show <run_id>` | show one run's metadata + KPIs |
| `roma-sim list-dispatchers` / `list-scenarios` | registry inspection |

## Run store layout

```
runs/
├── index.sqlite          # one row per run, one row per sweep
└── runs/<run_id>/
    ├── events.parquet    # the durable event log
    └── metadata.json     # human-readable mirror
```

DuckDB reads SQLite + Parquet natively, so any ad-hoc analysis is one SQL query
away.

## Determinism

Per-seed reproducibility, not bitwise determinism. All randomness flows through
one `numpy.random.Generator` constructed from the run seed. Two runs with the
same `(scenario_version, policy_version, seed)` produce identical event logs.
The multiprocess sweep runner is deterministic per-cell.

## Testing

```bash
pytest                       # 39 tests
ruff check src tests
mypy src
```
