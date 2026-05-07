"""Run store: SQLite metadata + Parquet event logs.

Layout under `<root>/`:
    index.sqlite              -- runs and sweeps tables
    runs/<run_id>/
        events.parquet        -- the durable event log
        metadata.json         -- redundant copy for grep-ability
        events.jsonl          -- optional, only if `also_jsonl=True`

The Parquet schema is flat: one row per event, with `payload` stored as a
JSON string. That keeps it easy to read into pandas, DuckDB, or any other
tool without schema evolution headaches.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

import pyarrow as pa
import pyarrow.parquet as pq

from roma_sim.domain import Event, EventKind

_SCHEMA_VERSION = 1

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sweeps (
    sweep_id    TEXT PRIMARY KEY,
    created_at  REAL NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    sweep_id            TEXT,
    scenario_name       TEXT NOT NULL,
    scenario_version    TEXT NOT NULL,
    dispatcher_name     TEXT NOT NULL,
    dispatcher_version  TEXT NOT NULL,
    seed                INTEGER NOT NULL,
    params_json         TEXT NOT NULL,
    kpis_json           TEXT NOT NULL,
    makespan_s          REAL NOT NULL,
    n_events            INTEGER NOT NULL,
    completed           INTEGER NOT NULL,
    wall_seconds        REAL NOT NULL,
    started_at          REAL NOT NULL,
    events_path         TEXT NOT NULL,
    FOREIGN KEY(sweep_id) REFERENCES sweeps(sweep_id)
);

CREATE INDEX IF NOT EXISTS ix_runs_sweep    ON runs(sweep_id);
CREATE INDEX IF NOT EXISTS ix_runs_scenario ON runs(scenario_name);
CREATE INDEX IF NOT EXISTS ix_runs_disp     ON runs(dispatcher_name);
"""

_PARQUET_SCHEMA = pa.schema(
    [
        ("t", pa.float64()),
        ("seq", pa.int64()),
        ("kind", pa.string()),
        ("payload", pa.string()),
    ]
)


@dataclass
class RunRecord:
    """One row of the runs table, plus the path to its event log."""

    run_id: str
    sweep_id: Optional[str]
    scenario_name: str
    scenario_version: str
    dispatcher_name: str
    dispatcher_version: str
    seed: int
    params: dict[str, Any]
    kpis: dict[str, Any]
    makespan_s: float
    n_events: int
    completed: bool
    wall_seconds: float
    started_at: float
    events_path: str

    def short_repr(self) -> str:
        return (
            f"{self.run_id}  "
            f"{self.scenario_name}/{self.dispatcher_name}/seed={self.seed}  "
            f"makespan={self.makespan_s / 3600:.2f}h"
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> RunRecord:
        return cls(
            run_id=row["run_id"],
            sweep_id=row["sweep_id"],
            scenario_name=row["scenario_name"],
            scenario_version=row["scenario_version"],
            dispatcher_name=row["dispatcher_name"],
            dispatcher_version=row["dispatcher_version"],
            seed=row["seed"],
            params=json.loads(row["params_json"]),
            kpis=json.loads(row["kpis_json"]),
            makespan_s=row["makespan_s"],
            n_events=row["n_events"],
            completed=bool(row["completed"]),
            wall_seconds=row["wall_seconds"],
            started_at=row["started_at"],
            events_path=row["events_path"],
        )


@dataclass
class RunStore:
    """File-backed store for runs and sweeps.

    Concurrent writers from the multiprocess sweep runner are safe because
    SQLite is set to WAL mode and each insert is its own transaction.
    """

    root: Path
    _db_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "runs").mkdir(parents=True, exist_ok=True)
        self._db_path = self.root / "index.sqlite"
        with self._connect() as conn:
            conn.executescript(_INIT_SQL)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "INSERT OR IGNORE INTO schema_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(_SCHEMA_VERSION)),
            )
            conn.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # -- sweeps -----------------------------------------------------------
    def new_sweep(self, description: str = "") -> str:
        sweep_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sweeps(sweep_id, created_at, description) VALUES (?, ?, ?)",
                (sweep_id, time.time(), description),
            )
            conn.commit()
        return sweep_id

    def list_sweeps(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT sweep_id, created_at, description FROM sweeps ORDER BY created_at DESC"
            )
            return [dict(r) for r in cur.fetchall()]

    # -- runs -------------------------------------------------------------
    def write_run(
        self,
        scenario_name: str,
        scenario_version: str,
        dispatcher_name: str,
        dispatcher_version: str,
        seed: int,
        params: dict[str, Any],
        kpis: dict[str, Any],
        events: Iterable[Event],
        wall_seconds: float,
        completed: bool,
        sweep_id: Optional[str] = None,
        also_jsonl: bool = False,
    ) -> RunRecord:
        """Persist a run's events and metadata. Returns the inserted record."""
        events = list(events)
        run_id = (
            f"{int(time.time())}-{scenario_name}-{dispatcher_name}-s{seed}-"
            f"{uuid.uuid4().hex[:6]}"
        )
        run_dir = self.root / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        events_path = run_dir / "events.parquet"
        _write_events_parquet(events, events_path)

        if also_jsonl:
            with (run_dir / "events.jsonl").open("w") as fh:
                for ev in events:
                    fh.write(json.dumps(ev.to_json()) + "\n")

        makespan_s = float(kpis.get("makespan_s", 0.0))

        record = RunRecord(
            run_id=run_id,
            sweep_id=sweep_id,
            scenario_name=scenario_name,
            scenario_version=scenario_version,
            dispatcher_name=dispatcher_name,
            dispatcher_version=dispatcher_version,
            seed=seed,
            params=dict(params),
            kpis=dict(kpis),
            makespan_s=makespan_s,
            n_events=len(events),
            completed=bool(completed),
            wall_seconds=wall_seconds,
            started_at=time.time(),
            events_path=str(events_path.relative_to(self.root)),
        )

        with (run_dir / "metadata.json").open("w") as fh:
            json.dump(asdict(record), fh, indent=2)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs(
                    run_id, sweep_id, scenario_name, scenario_version,
                    dispatcher_name, dispatcher_version, seed,
                    params_json, kpis_json, makespan_s, n_events,
                    completed, wall_seconds, started_at, events_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.sweep_id,
                    record.scenario_name,
                    record.scenario_version,
                    record.dispatcher_name,
                    record.dispatcher_version,
                    record.seed,
                    json.dumps(record.params, sort_keys=True),
                    json.dumps(record.kpis, sort_keys=True),
                    record.makespan_s,
                    record.n_events,
                    int(record.completed),
                    record.wall_seconds,
                    record.started_at,
                    record.events_path,
                ),
            )
            conn.commit()

        return record

    def get_run(self, run_id: str) -> Optional[RunRecord]:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
            return RunRecord.from_row(row) if row else None

    def list_runs(
        self,
        sweep_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[RunRecord]:
        sql = "SELECT * FROM runs"
        args: list[Any] = []
        if sweep_id is not None:
            sql += " WHERE sweep_id = ?"
            args.append(sweep_id)
        sql += " ORDER BY started_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        with self._connect() as conn:
            cur = conn.execute(sql, args)
            return [RunRecord.from_row(r) for r in cur.fetchall()]

    def load_events(self, run_id: str) -> list[Event]:
        rec = self.get_run(run_id)
        if rec is None:
            raise KeyError(f"unknown run_id {run_id!r}")
        return _read_events_parquet(self.root / rec.events_path)


def _write_events_parquet(events: Iterable[Event], path: Path) -> None:
    events = list(events)
    table = pa.table(
        {
            "t": [e.t for e in events],
            "seq": [e.seq for e in events],
            "kind": [e.kind.value for e in events],
            "payload": [json.dumps(dict(e.payload), sort_keys=True) for e in events],
        },
        schema=_PARQUET_SCHEMA,
    )
    pq.write_table(table, path)


def _read_events_parquet(path: Path) -> list[Event]:
    table = pq.read_table(path)
    rows = table.to_pylist()
    return [
        Event(
            t=float(r["t"]),
            seq=int(r["seq"]),
            kind=EventKind(r["kind"]),
            payload=json.loads(r["payload"]) if r["payload"] else {},
        )
        for r in rows
    ]
