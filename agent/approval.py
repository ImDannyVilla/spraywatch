"""The manager's decisions: approve a new date, confirm or reject a label. Standard library only.

Every decision is one transaction that checks first and refuses with a reason:

- `approve_alert`: only an open conflict alert, only by a policy approver, and
  only while the rules still find exactly that conflict. It moves the harvest or
  entry to the proposed date or time and writes the change to the queue.
- `confirm_label` / `reject_label`: only an `extracted` label. Confirming one
  with an unverified fact needs the approver to say they checked the label.

A refusal is logged as `approval_refused` and raised as `Refused`.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date
from pathlib import Path

from agent import db, store

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUEUE = Path(os.environ.get("SPRAYWATCH_QUEUE", str(ROOT / "state" / "queue")))
QUEUE_SCHEMA = "spraywatch.queue/1"


class Refused(Exception):
    """A decision the contract doesn't allow. The message says why, for the page's banner."""


def _refuse(conn: sqlite3.Connection, actor: str, action: str, reason: str, **ids) -> None:
    with conn:
        db.log_event(conn, actor or "unknown", "approval_refused", {"action": action, "reason": reason, **ids})
    raise Refused(reason)


def _check_approver(conn: sqlite3.Connection, policy: dict, approver: str, action: str, **ids) -> None:
    if approver not in policy["approvers"]:
        _refuse(conn, approver, action, "not an approver in policy.json", **ids)


def approve_alert(conn: sqlite3.Connection, policy: dict, alert_id: int, approver: str, today: date,
                  queue_dir: Path = DEFAULT_QUEUE) -> Path:
    """Move the harvest or entry to the alert's earliest legal date or time. Returns the queue file."""
    action = "approve_alert"
    _check_approver(conn, policy, approver, action, alert_id=alert_id)
    alert = conn.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
    if alert is None:
        _refuse(conn, approver, action, "no such alert", alert_id=alert_id)
    if alert["state"] != "open":
        _refuse(conn, approver, action, f"the alert is already {alert['state']}", alert_id=alert_id)
    if alert["kind"] not in ("harvest_conflict", "entry_conflict"):
        _refuse(conn, approver, action, "this alert has no date to approve; fix the label or the spray log",
                alert_id=alert_id)
    current = {finding.key for finding in store.evaluate(conn, policy, today)}
    if alert["alert_key"] not in current:
        _refuse(conn, approver, action, "the schedule or a label changed since this alert; run the check again",
                alert_id=alert_id)

    queue_dir.mkdir(parents=True, exist_ok=True)
    queue_file = queue_dir / f"schedule-change-{alert_id}.json"
    decided_at = db.now()
    change = {"schema": QUEUE_SCHEMA, "alert_id": alert_id, "kind": alert["kind"], "block_id": alert["block_id"],
              "from": alert["scheduled"], "to": alert["earliest"], "reason": alert["reason"],
              "spray_id": alert["spray_id"], "label_id": alert["label_id"], "approver": approver,
              "approved_at": decided_at}
    if alert["kind"] == "harvest_conflict":
        change["harvest_id"] = alert["harvest_id"]
    else:
        change["entry_id"] = alert["entry_id"]
    with conn:
        if alert["kind"] == "harvest_conflict":
            conn.execute("UPDATE harvests SET planned_date = ?, updated_at = ? WHERE harvest_id = ?",
                         (alert["earliest"], decided_at, alert["harvest_id"]))
        else:
            conn.execute("UPDATE crew_entries SET planned_at = ?, updated_at = ? WHERE entry_id = ?",
                         (alert["earliest"], decided_at, alert["entry_id"]))
        conn.execute("UPDATE alerts SET state = 'approved', decided_by = ?, decided_at = ? WHERE alert_id = ?",
                     (approver, decided_at, alert_id))
        db.log_event(conn, approver, "alert_approved", {"alert_id": alert_id, "from": alert["scheduled"],
                                                        "to": alert["earliest"]})
        # Written once, never overwritten: "x" fails if the file is already there, and the transaction rolls back.
        with queue_file.open("x", encoding="utf-8") as handle:
            json.dump(change, handle, indent=2, sort_keys=True)
            handle.write("\n")
        db.log_event(conn, approver, "queued", {"alert_id": alert_id, "file": queue_file.name})
    return queue_file


def confirm_label(conn: sqlite3.Connection, policy: dict, label_id: int, approver: str,
                  checked_myself: bool = False) -> None:
    action = "confirm_label"
    _check_approver(conn, policy, approver, action, label_id=label_id)
    label = conn.execute("SELECT * FROM labels WHERE label_id = ?", (label_id,)).fetchone()
    if label is None:
        _refuse(conn, approver, action, "no such label", label_id=label_id)
    if label["state"] != "extracted":
        _refuse(conn, approver, action, f"the label is already {label['state']}", label_id=label_id)
    unverified = conn.execute("SELECT COUNT(*) AS n FROM label_facts WHERE label_id = ? AND quote_verified = 0",
                              (label_id,)).fetchone()["n"]
    if unverified and not checked_myself:
        _refuse(conn, approver, action,
                f"{unverified} fact{'s' if unverified != 1 else ''} couldn't be matched to the label text; "
                "check them against the label and tick the box", label_id=label_id)
    with conn:
        conn.execute("UPDATE labels SET state = 'confirmed', decided_by = ?, decided_at = ? WHERE label_id = ?",
                     (approver, db.now(), label_id))
        db.log_event(conn, approver, "label_confirmed", {"label_id": label_id, "unverified": unverified,
                                                         "checked_myself": bool(checked_myself)})


def reject_label(conn: sqlite3.Connection, policy: dict, label_id: int, approver: str) -> None:
    action = "reject_label"
    _check_approver(conn, policy, approver, action, label_id=label_id)
    label = conn.execute("SELECT * FROM labels WHERE label_id = ?", (label_id,)).fetchone()
    if label is None:
        _refuse(conn, approver, action, "no such label", label_id=label_id)
    if label["state"] != "extracted":
        _refuse(conn, approver, action, f"the label is already {label['state']}", label_id=label_id)
    with conn:
        conn.execute("UPDATE labels SET state = 'rejected', decided_by = ?, decided_at = ? WHERE label_id = ?",
                     (approver, db.now(), label_id))
        db.log_event(conn, approver, "label_rejected", {"label_id": label_id})
