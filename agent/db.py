"""SprayWatch's SQLite file: the tables and the event log. Standard library only.

One file, `state/spraywatch.db` by default, exactly as contracts/README.md
"SQLite tables" says. No row is ever deleted, and `events` is append-only.

- `connect(path)` opens the file and creates the tables on first use.
- `log_event(...)` appends to the audit trail.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = Path(os.environ.get("SPRAYWATCH_DB", str(ROOT / "state" / "spraywatch.db")))

LABEL_STATES = ("extracted", "confirmed", "rejected")
ALERT_KINDS = ("harvest_conflict", "entry_conflict", "unknown_product", "label_unconfirmed", "crop_not_on_label")
ALERT_STATES = ("open", "approved", "resolved")
EVENT_KINDS = (
    "label_extracted",
    "label_failed",
    "label_confirmed",
    "label_rejected",
    "spray_logged",
    "schedule_imported",
    "alert_raised",
    "alert_resolved",
    "alert_approved",
    "approval_refused",
    "card_posted",
    "digest_posted",
    "queued",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS blocks (
    block_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    crop TEXT NOT NULL,
    acres REAL
);
CREATE TABLE IF NOT EXISTS labels (
    label_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT NOT NULL,
    epa_reg_no TEXT,
    product_type TEXT NOT NULL,
    state TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_sha256 TEXT NOT NULL UNIQUE,
    pages_json TEXT NOT NULL,
    model TEXT NOT NULL,
    extracted_at TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS label_facts (
    fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    label_id INTEGER NOT NULL REFERENCES labels(label_id),
    crop TEXT NOT NULL,
    kind TEXT NOT NULL,
    condition TEXT,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    hours REAL NOT NULL,
    page INTEGER,
    line INTEGER,
    quote TEXT NOT NULL,
    quote_verified INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sprays (
    spray_id INTEGER PRIMARY KEY AUTOINCREMENT,
    block_id TEXT NOT NULL REFERENCES blocks(block_id),
    product TEXT NOT NULL,
    epa_reg_no TEXT,
    applied_at TEXT NOT NULL,
    applicator TEXT,
    source TEXT NOT NULL,
    logged_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS harvests (
    harvest_id TEXT PRIMARY KEY,
    block_id TEXT NOT NULL REFERENCES blocks(block_id),
    planned_date TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS crew_entries (
    entry_id TEXT PRIMARY KEY,
    block_id TEXT NOT NULL REFERENCES blocks(block_id),
    crew TEXT NOT NULL,
    task TEXT,
    planned_at TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    block_id TEXT NOT NULL,
    spray_id INTEGER,
    label_id INTEGER,
    harvest_id TEXT,
    entry_id TEXT,
    scheduled TEXT,
    earliest TEXT,
    reason TEXT,
    interval_hours REAL,
    created_at TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    actor TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS facts_by_label ON label_facts (label_id);
CREATE INDEX IF NOT EXISTS sprays_by_block ON sprays (block_id, applied_at);
CREATE INDEX IF NOT EXISTS events_by_kind ON events (kind);
"""


def now() -> str:
    """Farm-local time to the minute, as the contract says."""
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


def connect(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    """Open the database, creating its folder and tables on first use."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def connect_readonly(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    """Open the database read-only, for the local page."""
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def log_event(conn: sqlite3.Connection, actor: str, kind: str, detail: dict | None = None,
              at: str | None = None) -> None:
    """Append one event. `detail` is small JSON: IDs and dates, no label text."""
    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown event kind: {kind}")
    conn.execute("INSERT INTO events (at, actor, kind, detail) VALUES (?, ?, ?, ?)",
                 (at or now(), actor, kind, json.dumps(detail or {}, sort_keys=True)))


def has_event(conn: sqlite3.Connection, kind: str, detail_match: dict) -> bool:
    """Whether an event of this kind exists with these detail values."""
    for row in conn.execute("SELECT detail FROM events WHERE kind = ?", (kind,)):
        detail = json.loads(row["detail"])
        if all(detail.get(key) == value for key, value in detail_match.items()):
            return True
    return False
