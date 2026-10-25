#!/usr/bin/env python3
"""One check pass: the rules into alerts, then any card that's due. Standard library only.

    python3 agent/check.py            # one pass, as the recurring job runs it
    python3 agent/check.py --morning  # one pass that posts today's digest even before morning_time

A pass:

1. Applies the rules (`agent/rules.py`) to the whole farm.
2. Raises an alert for every finding not raised before, and resolves every open
   alert whose finding is gone (the schedule or a label changed).
3. Posts an alert card for every open alert without one, a spray card for every
   spray whose block is still closed, and the morning digest once a day.

A card is logged as posted only once Slack takes it. With Slack unset, cards
wait and go out on the first pass after it's set.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import card, db, rules, slack, store  # noqa: E402
from policy import policy as policy_loader  # noqa: E402

DEFAULT_BASE_URL = "http://127.0.0.1:8091"


@dataclass
class PassReport:
    raised: list[int] = field(default_factory=list)
    resolved: list[int] = field(default_factory=list)
    posted: list[str] = field(default_factory=list)
    waiting: int = 0
    slack_error: str | None = None
    card_errors: list[str] = field(default_factory=list)


def sync_alerts(conn: sqlite3.Connection, findings: list[rules.Finding], report: PassReport) -> None:
    keys = {finding.key: finding for finding in findings}
    with conn:
        for key, finding in keys.items():
            if conn.execute("SELECT 1 FROM alerts WHERE alert_key = ?", (key,)).fetchone():
                continue
            cursor = conn.execute(
                "INSERT INTO alerts (alert_key, kind, state, block_id, spray_id, label_id, harvest_id, entry_id, "
                "scheduled, earliest, reason, interval_hours, created_at) "
                "VALUES (?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (key, finding.kind, finding.block_id, finding.spray_id, finding.label_id, finding.harvest_id,
                 finding.entry_id, finding.scheduled, finding.earliest, finding.reason, finding.interval_hours,
                 db.now()))
            report.raised.append(cursor.lastrowid)
            db.log_event(conn, "check", "alert_raised", {"alert_id": cursor.lastrowid, "kind": finding.kind,
                                                          "block_id": finding.block_id})
        for row in conn.execute("SELECT alert_id, alert_key FROM alerts WHERE state = 'open'").fetchall():
            if row["alert_key"] not in keys:
                conn.execute("UPDATE alerts SET state = 'resolved', decided_by = 'check', decided_at = ? "
                             "WHERE alert_id = ?", (db.now(), row["alert_id"]))
                report.resolved.append(row["alert_id"])
                db.log_event(conn, "check", "alert_resolved", {"alert_id": row["alert_id"]})


def open_spray_cards(conn: sqlite3.Connection, policy: dict, now: datetime) -> list[tuple[int, int, datetime]]:
    """(spray, label, REI end) for every spray with a confirmed label whose block is still closed."""
    state = store.load_state(conn)
    aliases = {rules.crop_key(k, {}): rules.crop_key(v, {}) for k, v in policy.get("crop_aliases", {}).items()}
    blocks = {block.block_id: block for block in state["blocks"]}
    due = []
    for spray in state["sprays"]:
        label, standing = rules.match_label(spray, state["labels"])
        if standing != "confirmed" or spray.block_id not in blocks:
            continue
        limits = rules.intervals(label, blocks[spray.block_id].crop, aliases)
        if limits is None:
            continue
        rei_end = rules.earliest_entry(spray, limits[1])
        if rei_end > now:
            due.append((spray.spray_id, label.label_id, rei_end))
    return due


def post_due(conn: sqlite3.Connection, policy: dict, poster: slack.Poster, base_url: str, now: datetime,
             force_digest: bool, report: PassReport) -> None:
    jobs = []
    for row in conn.execute("SELECT alert_id FROM alerts WHERE state = 'open' ORDER BY alert_id"):
        if not db.has_event(conn, "card_posted", {"card": "alert", "alert_id": row["alert_id"]}):
            jobs.append(({"card": "alert", "alert_id": row["alert_id"]},
                         lambda alert_id=row["alert_id"]: card.alert_card(conn, policy, alert_id, base_url)))
    for spray_id, label_id, rei_end in open_spray_cards(conn, policy, now):
        if not db.has_event(conn, "card_posted", {"card": "spray", "spray_id": spray_id}):
            jobs.append(({"card": "spray", "spray_id": spray_id},
                         lambda s=spray_id, l=label_id, e=rei_end: card.spray_card(conn, policy, s, e, l, base_url)))
    today = now.date()
    morning = time.fromisoformat(policy["morning_time"])
    if (force_digest or now.time() >= morning) and not db.has_event(conn, "digest_posted",
                                                                    {"date": today.isoformat()}):
        open_ids = [row["alert_id"] for row in
                    conn.execute("SELECT alert_id FROM alerts WHERE state = 'open' ORDER BY alert_id")]
        jobs.append(({"digest": today.isoformat(), "open": len(open_ids)},
                     lambda ids=open_ids: card.digest_card(conn, policy, today, ids, base_url)))
    for detail, build in jobs:
        try:
            text = build()
        except card.CardError as error:
            report.card_errors.append(f"{detail}: {error}")
            continue
        try:
            ts = poster(text)
        except slack.SlackError as error:
            report.slack_error = str(error)
            report.waiting += 1
            continue
        if ts is None:
            report.waiting += 1
            continue
        with conn:
            if "digest" in detail:
                db.log_event(conn, "check", "digest_posted",
                             {"date": detail["digest"], "open": detail["open"], "ts": ts})
            else:
                db.log_event(conn, "check", "card_posted", {**detail, "ts": ts})
        report.posted.append(detail.get("card", "digest"))


def run_pass(conn: sqlite3.Connection, policy: dict, poster: slack.Poster, base_url: str = DEFAULT_BASE_URL,
             now: datetime | None = None, force_digest: bool = False) -> PassReport:
    now = now or datetime.now().replace(second=0, microsecond=0)
    report = PassReport()
    sync_alerts(conn, store.evaluate(conn, policy, now.date()), report)
    post_due(conn, policy, poster, base_url, now, force_digest, report)
    return report


def describe(report: PassReport) -> str:
    parts = [f"{len(report.raised)} raised", f"{len(report.resolved)} resolved", f"{len(report.posted)} posted"]
    if report.waiting:
        parts.append(f"{report.waiting} waiting for Slack")
    if report.slack_error:
        parts.append(report.slack_error)
    parts.extend(f"card refused {error}" for error in report.card_errors)
    return ", ".join(parts)


def settings_from_env() -> tuple[Path, Path, str]:
    env = os.environ.get
    return (Path(env("SPRAYWATCH_DB", str(db.DEFAULT_DB))),
            Path(env("SPRAYWATCH_POLICY", str(policy_loader.POLICY))),
            env("SPRAYWATCH_BASE_URL", DEFAULT_BASE_URL))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--morning", action="store_true", help="post today's digest now, if not posted yet")
    args = parser.parse_args(argv)
    db_path, policy_path, base_url = settings_from_env()
    conn = db.connect(db_path)
    report = run_pass(conn, policy_loader.load(policy_path), slack.poster_from_env(), base_url,
                      force_digest=args.morning)
    print(f"check: {describe(report)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
