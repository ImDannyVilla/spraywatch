"""Reading and writing the farm's records: labels, sprays, blocks and the schedule. Standard library only.

Everything that goes into SQLite, other than alerts and approvals, goes through
here, so the inbox, the local page's spray form and the tests write rows the
same way. `load_state` reads them back as `agent.rules` records.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from agent import db, rules
from labels import extract, reader

BLOCK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}")
SCHEDULE_ID = BLOCK_ID
MAX_TEXT = 80


class RecordError(ValueError):
    """A row the contract doesn't allow. The message names the field, never the whole row."""


@dataclass
class ImportReport:
    kind: str
    added: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _text(value, name: str, required: bool = True) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        if required:
            raise RecordError(f"{name} is empty")
        return None
    if len(text) > MAX_TEXT:
        raise RecordError(f"{name} is over {MAX_TEXT} characters")
    return text


def _id(value, name: str) -> str:
    text = str(value or "").strip()
    if not SCHEDULE_ID.fullmatch(text):
        raise RecordError(f"{name} must be letters, digits, - or _")
    return text


def _block_exists(conn: sqlite3.Connection, block_id: str) -> None:
    if conn.execute("SELECT 1 FROM blocks WHERE block_id = ?", (block_id,)).fetchone() is None:
        raise RecordError(f"no such block: {block_id}")


# Labels -------------------------------------------------------------------------------------

def label_by_sha(conn: sqlite3.Connection, sha256: str) -> int | None:
    row = conn.execute("SELECT label_id FROM labels WHERE source_sha256 = ?", (sha256,)).fetchone()
    return row["label_id"] if row else None


def save_label(conn: sqlite3.Connection, source: extract.LabelSource, read: reader.ReadLabel,
               model_name: str) -> int:
    """Store a label the model read, as `extracted`. The same file is stored once."""
    existing = label_by_sha(conn, source.sha256)
    if existing is not None:
        return existing
    with conn:
        cursor = conn.execute(
            "INSERT INTO labels (product_name, epa_reg_no, product_type, state, source_file, source_sha256, "
            "pages_json, model, extracted_at) VALUES (?, ?, ?, 'extracted', ?, ?, ?, ?, ?)",
            (read.product_name, read.epa_reg_no, read.product_type, source.path.name, source.sha256,
             json.dumps([list(page) for page in source.pages]), model_name, db.now()))
        label_id = cursor.lastrowid
        for fact in read.facts:
            conn.execute(
                "INSERT INTO label_facts (label_id, crop, kind, condition, value, unit, hours, page, line, quote, "
                "quote_verified) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (label_id, fact.crop, fact.kind, fact.condition, fact.value, fact.unit, fact.hours, fact.page, fact.line,
                 fact.quote, int(fact.quote_verified)))
        verified = sum(1 for fact in read.facts if fact.quote_verified)
        db.log_event(conn, "label-reader", "label_extracted",
                     {"label_id": label_id, "sha256": source.sha256, "facts": len(read.facts), "verified": verified,
                      "seconds": read.reply_seconds})
    return label_id


# Blocks, sprays and the schedule ------------------------------------------------------------

def upsert_block(conn: sqlite3.Connection, block_id, name, crop, acres=None) -> bool:
    """Returns True if the block is new."""
    block_id = _id(block_id, "block_id")
    name, crop = _text(name, "name"), _text(crop, "crop")
    acres = float(acres) if str(acres or "").strip() else None
    new = conn.execute("SELECT 1 FROM blocks WHERE block_id = ?", (block_id,)).fetchone() is None
    conn.execute("INSERT INTO blocks (block_id, name, crop, acres) VALUES (?, ?, ?, ?) ON CONFLICT(block_id) "
                 "DO UPDATE SET name = excluded.name, crop = excluded.crop, acres = excluded.acres",
                 (block_id, name, crop, acres))
    return new


def add_spray(conn: sqlite3.Connection, block_id, product, epa_reg_no, applied_at, applicator, source: str,
              actor: str = "inbox") -> int | None:
    """Log one spray. Returns its ID, or None if the same spray is already logged."""
    block_id = _id(block_id, "block_id")
    _block_exists(conn, block_id)
    product = _text(product, "product")
    epa = rules.reg_key(_text(epa_reg_no, "epa_reg_no", required=False))
    try:
        applied = rules.fmt_datetime(rules.parse_datetime(str(applied_at or "")))
    except ValueError:
        raise RecordError("applied_at must be YYYY-MM-DDTHH:MM") from None
    applicator = _text(applicator, "applicator", required=False)
    for row in conn.execute("SELECT product FROM sprays WHERE block_id = ? AND applied_at = ?", (block_id, applied)):
        if rules.product_key(row["product"]) == rules.product_key(product):
            return None
    cursor = conn.execute(
        "INSERT INTO sprays (block_id, product, epa_reg_no, applied_at, applicator, source, logged_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", (block_id, product, epa, applied, applicator, source, db.now()))
    db.log_event(conn, actor, "spray_logged", {"spray_id": cursor.lastrowid, "block_id": block_id,
                                                "applied_at": applied, "source": source})
    return cursor.lastrowid


def upsert_harvest(conn: sqlite3.Connection, harvest_id, block_id, planned_date) -> str:
    """'added', 'updated', or 'kept' when the harvest is no longer `planned` or didn't change."""
    harvest_id, block_id = _id(harvest_id, "harvest_id"), _id(block_id, "block_id")
    _block_exists(conn, block_id)
    try:
        planned = rules.fmt_date(rules.parse_date(str(planned_date or "")))
    except ValueError:
        raise RecordError("planned_date must be YYYY-MM-DD") from None
    row = conn.execute("SELECT * FROM harvests WHERE harvest_id = ?", (harvest_id,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO harvests (harvest_id, block_id, planned_date, status, updated_at) "
                     "VALUES (?, ?, ?, 'planned', ?)", (harvest_id, block_id, planned, db.now()))
        return "added"
    if row["status"] != "planned" or (row["block_id"], row["planned_date"]) == (block_id, planned):
        return "kept"
    conn.execute("UPDATE harvests SET block_id = ?, planned_date = ?, updated_at = ? WHERE harvest_id = ?",
                 (block_id, planned, db.now(), harvest_id))
    return "updated"


def upsert_entry(conn: sqlite3.Connection, entry_id, block_id, crew, task, planned_at) -> str:
    entry_id, block_id = _id(entry_id, "entry_id"), _id(block_id, "block_id")
    _block_exists(conn, block_id)
    crew, task = _text(crew, "crew"), _text(task, "task", required=False)
    try:
        planned = rules.fmt_datetime(rules.parse_datetime(str(planned_at or "")))
    except ValueError:
        raise RecordError("planned_at must be YYYY-MM-DDTHH:MM") from None
    row = conn.execute("SELECT * FROM crew_entries WHERE entry_id = ?", (entry_id,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO crew_entries (entry_id, block_id, crew, task, planned_at, status, updated_at) "
                     "VALUES (?, ?, ?, ?, ?, 'planned', ?)", (entry_id, block_id, crew, task, planned, db.now()))
        return "added"
    if row["status"] != "planned" or (row["block_id"], row["crew"], row["task"], row["planned_at"]) == (
            block_id, crew, task, planned):
        return "kept"
    conn.execute("UPDATE crew_entries SET block_id = ?, crew = ?, task = ?, planned_at = ?, updated_at = ? "
                 "WHERE entry_id = ?", (block_id, crew, task, planned, db.now(), entry_id))
    return "updated"


CSV_KINDS = {
    "blocks": ("block_id", "name", "crop", "acres"),
    "sprays": ("block_id", "product", "epa_reg_no", "applied_at", "applicator"),
    "harvests": ("harvest_id", "block_id", "planned_date"),
    "crew": ("entry_id", "block_id", "crew", "task", "planned_at"),
}


def csv_kind(path: Path) -> str | None:
    """Which schedule file this is, by its name, as the contract's inbox table says."""
    stem = path.stem.lower()
    if path.suffix.lower() != ".csv":
        return None
    if stem == "blocks":
        return "blocks"
    for kind in ("sprays", "harvests", "crew"):
        if stem.startswith(kind):
            return kind
    return None


def import_csv(conn: sqlite3.Connection, path: Path, sha256: str) -> ImportReport:
    """One schedule file into SQLite, in one transaction. Bad rows are skipped and reported by line."""
    kind = csv_kind(path)
    if kind is None:
        raise RecordError(f"not a schedule file: {path.name}")
    report = ImportReport(kind)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
        columns = set(rows[0]) if rows else set()
    missing = [name for name in CSV_KINDS[kind] if name not in columns and name not in ("acres", "epa_reg_no",
                                                                                          "applicator", "task")]
    if rows and missing:
        raise RecordError(f"{path.name} is missing columns: {', '.join(missing)}")
    with conn:
        for number, row in enumerate(rows, start=2):
            try:
                if kind == "blocks":
                    new = upsert_block(conn, row.get("block_id"), row.get("name"), row.get("crop"), row.get("acres"))
                    outcome = "added" if new else "updated"
                elif kind == "sprays":
                    spray_id = add_spray(conn, row.get("block_id"), row.get("product"), row.get("epa_reg_no"),
                                         row.get("applied_at"), row.get("applicator"), source=path.name)
                    outcome = "added" if spray_id else "kept"
                elif kind == "harvests":
                    outcome = upsert_harvest(conn, row.get("harvest_id"), row.get("block_id"), row.get("planned_date"))
                else:
                    outcome = upsert_entry(conn, row.get("entry_id"), row.get("block_id"), row.get("crew"),
                                           row.get("task"), row.get("planned_at"))
            except (RecordError, ValueError) as error:
                report.errors.append(f"{path.name} line {number}: {error}")
                continue
            if outcome == "added":
                report.added += 1
            elif outcome == "updated":
                report.updated += 1
            else:
                report.skipped += 1
        db.log_event(conn, "inbox", "schedule_imported",
                     {"file": path.name, "sha256": sha256, "kind": kind, "added": report.added,
                      "updated": report.updated, "skipped": report.skipped, "errors": len(report.errors)})
    return report


# Reading the state for the rules ------------------------------------------------------------

def load_state(conn: sqlite3.Connection) -> dict:
    blocks = [rules.Block(r["block_id"], r["name"], r["crop"]) for r in conn.execute("SELECT * FROM blocks")]
    facts: dict[int, list[rules.Fact]] = {}
    for r in conn.execute("SELECT * FROM label_facts ORDER BY fact_id"):
        facts.setdefault(r["label_id"], []).append(rules.Fact(r["crop"], r["kind"], r["hours"], r["fact_id"]))
    labels = [rules.Label(r["label_id"], r["product_name"], r["epa_reg_no"], r["product_type"], r["state"],
                          tuple(facts.get(r["label_id"], ()))) for r in conn.execute("SELECT * FROM labels")]
    sprays = [rules.Spray(r["spray_id"], r["block_id"], r["product"], r["epa_reg_no"],
                          rules.parse_datetime(r["applied_at"])) for r in conn.execute("SELECT * FROM sprays")]
    harvests = [rules.Harvest(r["harvest_id"], r["block_id"], rules.parse_date(r["planned_date"]))
                for r in conn.execute("SELECT * FROM harvests WHERE status = 'planned'")]
    entries = [rules.Entry(r["entry_id"], r["block_id"], r["crew"], rules.parse_datetime(r["planned_at"]))
               for r in conn.execute("SELECT * FROM crew_entries WHERE status = 'planned'")]
    return {"blocks": blocks, "labels": labels, "sprays": sprays, "harvests": harvests, "entries": entries}


def evaluate(conn: sqlite3.Connection, policy: dict, today: date) -> list[rules.Finding]:
    return rules.evaluate(policy=policy, today=today, **load_state(conn))
