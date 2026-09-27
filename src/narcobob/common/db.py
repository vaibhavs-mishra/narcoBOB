"""SQLite access: schema, connection settings and the tiny key-value helpers.

SQLite in WAL mode is the whole persistence layer. Keep write transactions short.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY, type TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
  cell TEXT NOT NULL, ts TEXT NOT NULL, bucket INTEGER NOT NULL, source TEXT NOT NULL,
  quantity_g REAL, substance TEXT, meta TEXT, wall_ingested_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_cell_bucket ON events(cell, bucket);
CREATE INDEX IF NOT EXISTS ix_events_source_bucket ON events(source, bucket);

CREATE TABLE IF NOT EXISTS cell_scores (
  cell TEXT PRIMARY KEY, score INTEGER NOT NULL, severity TEXT NOT NULL,
  z_accel REAL, z_div REAL, z_spill REAL, gi_star REAL,
  c_accel REAL, c_div REAL, c_spill REAL, c_gi REAL,
  support INTEGER NOT NULL, confidence TEXT NOT NULL,
  data_version INTEGER NOT NULL, sim_ts TEXT NOT NULL, wall_updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
  alert_id TEXT PRIMARY KEY, cell TEXT NOT NULL, severity TEXT NOT NULL,
  score INTEGER NOT NULL, reason TEXT NOT NULL,
  run_id TEXT, final_severity TEXT, verdict TEXT,
  sim_ts TEXT NOT NULL, wall_created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
  run_id TEXT PRIMARY KEY, status TEXT NOT NULL,
  alert_ids TEXT NOT NULL, cells TEXT NOT NULL,
  data_version INTEGER NOT NULL, wall_started_at TEXT, wall_finished_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_steps (
  step_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
  agent_id TEXT NOT NULL, status TEXT NOT NULL, source TEXT,
  attempt INTEGER NOT NULL DEFAULT 1, tool_calls INTEGER NOT NULL DEFAULT 0,
  log TEXT, wall_started_at TEXT NOT NULL, wall_finished_at TEXT
);

CREATE TABLE IF NOT EXISTS tool_calls (
  call_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, run_id TEXT, step_id TEXT, agent_id TEXT,
  tool TEXT NOT NULL, tool_version TEXT NOT NULL, args_hash TEXT NOT NULL,
  ok INTEGER NOT NULL, error_code TEXT, duration_ms INTEGER NOT NULL, wall_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
  finding_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_id TEXT NOT NULL,
  agent_id TEXT NOT NULL, kind TEXT NOT NULL,
  cell TEXT, payload TEXT NOT NULL,
  source TEXT NOT NULL, idempotency_key TEXT UNIQUE, wall_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
  report_id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE, markdown TEXT NOT NULL,
  recommendations TEXT NOT NULL,
  provenance_ratio REAL, source TEXT NOT NULL, idempotency_key TEXT UNIQUE, wall_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection with the settings every process must use."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(path: Path) -> sqlite3.Connection:
    """Create the schema if needed and return an open connection."""
    conn = connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO kv(key, value) VALUES ('data_version', '0')")
    conn.commit()
    return conn


def kv_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO kv(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def data_version(conn: sqlite3.Connection) -> int:
    return int(kv_get(conn, "data_version") or 0)
