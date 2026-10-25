#!/usr/bin/env python3
"""The folder watcher: label files and schedule CSVs in, then a check pass. Standard library only.

    python3 agent/watch.py --once   # one pass over the inbox, then the check
    python3 agent/watch.py          # the same every POLL_SECONDS (default 10)

Each file is handled once, by its SHA-256, as contracts/README.md "The inbox"
says. A label the model can't read is logged as `label_failed` and left for a
person; drop a better scan or photo in to try again. A PDF whose text isn't
there yet (in the sandbox, until the host writes its sidecar) is tried again on
the next pass.

| Variable | Default | What |
| --- | --- | --- |
| `SPRAYWATCH_INBOX` | `state/inbox` | The folder to watch |
| `SPRAYWATCH_DB` | `state/spraywatch.db` | SQLite |
| `SPRAYWATCH_POLICY` | `policy/policy.json` | Approvers, times, card templates |
| `SPRAYWATCH_MODEL_ENV` | unset | An env file with `MODEL_URL`, `MODEL_NAME`, `MODEL_API_KEY` |
| `SPRAYWATCH_FAKE_REPLIES` | unset | A folder of `<label stem>.json` replies: no model, for the demo |
| `POLL_SECONDS` | `10` | The loop's interval |
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import check, db, slack, store  # noqa: E402
from labels import extract, model as model_module, reader  # noqa: E402
from policy import policy as policy_loader  # noqa: E402

DEFAULT_INBOX = ROOT / "state" / "inbox"


@dataclass
class InboxReport:
    labels: list[int] = field(default_factory=list)
    imports: list[store.ImportReport] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    waiting: list[str] = field(default_factory=list)  # PDFs whose text the host hasn't written yet
    ignored: list[str] = field(default_factory=list)


class ModelSource:
    """Which model reads a label: the real one, or a fake reply chosen by file name."""

    def __init__(self, fake_replies: Path | None = None, env_file: Path | None = None):
        self.fake = model_module.FakeReplies(fake_replies) if fake_replies else None
        self.env_file = env_file
        self._client = None

    def for_label(self, path: Path) -> model_module.Model:
        if self.fake:
            return self.fake.for_label(path)
        if self._client is None:
            self._client = model_module.ChatClient.from_env(self.env_file)
        return self._client

    @classmethod
    def from_env(cls) -> "ModelSource":
        fake, env_file = os.environ.get("SPRAYWATCH_FAKE_REPLIES"), os.environ.get("SPRAYWATCH_MODEL_ENV")
        return cls(Path(fake) if fake else None, Path(env_file) if env_file else None)


def handled(conn: sqlite3.Connection, sha256: str) -> bool:
    return any(db.has_event(conn, kind, {"sha256": sha256})
               for kind in ("label_extracted", "label_failed", "schedule_imported"))


def scan(conn: sqlite3.Connection, inbox: Path, models: ModelSource, report: InboxReport | None = None) -> InboxReport:
    """Every new file in the inbox, oldest first. Schedule files go before labels, blocks before the rest."""
    report = report or InboxReport()
    if not inbox.is_dir():
        return report
    files = [path for path in inbox.iterdir() if path.is_file() and not path.name.startswith(".")]
    order = {"blocks": 0, "harvests": 1, "crew": 1, "sprays": 3}

    def rank(path: Path) -> tuple:
        kind = store.csv_kind(path)
        return (order.get(kind, 2), path.stat().st_mtime, path.name)

    for path in sorted(files, key=rank):
        kind = store.csv_kind(path)
        if extract.is_sidecar(path):
            continue  # read with its PDF
        if kind is None and path.suffix.lower() not in extract.LABEL_SUFFIXES:
            report.ignored.append(path.name)
            continue
        sha = extract.sha256(path)
        if handled(conn, sha):
            continue
        if kind:
            try:
                report.imports.append(store.import_csv(conn, path, sha))
            except (store.RecordError, ValueError, UnicodeDecodeError) as error:
                report.failed.append(f"{path.name}: {error}")
                with conn:
                    db.log_event(conn, "inbox", "schedule_imported",
                                 {"file": path.name, "sha256": sha, "kind": kind, "failed": str(error)[:200]})
            continue
        try:
            source = extract.load(path)
            model = models.for_label(path)
            report.labels.append(store.save_label(conn, source, reader.read(source, model), model.name))
        except extract.NotReady as error:
            report.waiting.append(f"{path.name}: {error}")
        except (extract.ExtractError, reader.ReplyError, model_module.ModelError) as error:
            report.failed.append(f"{path.name}: {error}")
            with conn:
                db.log_event(conn, "label-reader", "label_failed",
                             {"file": path.name, "sha256": sha, "error": str(error)[:200]})
    return report


def describe(report: InboxReport) -> str:
    parts = []
    if report.labels:
        parts.append(f"{len(report.labels)} label{'s' if len(report.labels) != 1 else ''} read")
    for item in report.imports:
        parts.append(f"{item.kind}: {item.added} added, {item.updated} updated"
                     + (f", {len(item.errors)} bad rows" if item.errors else ""))
    parts.extend(f"failed {item}" for item in report.failed)
    parts.extend(f"waiting {item}" for item in report.waiting)
    return "; ".join(parts) or "nothing new"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    args = parser.parse_args(argv)
    inbox = Path(os.environ.get("SPRAYWATCH_INBOX", str(DEFAULT_INBOX)))
    db_path, policy_path, base_url = check.settings_from_env()
    interval = float(os.environ.get("POLL_SECONDS", "10"))
    poster = slack.poster_from_env()
    models = ModelSource.from_env()
    conn = db.connect(db_path)
    inbox.mkdir(parents=True, exist_ok=True)
    if poster is slack.unconfigured_poster:
        print("watch: Slack is not configured (SLACK_BOT_TOKEN and SLACK_CHANNEL); cards wait until it is",
              flush=True)
    last = None
    while True:
        try:
            report = scan(conn, inbox, models)
            for item in report.imports:
                for error in item.errors:
                    print(f"watch: {error}", flush=True)
            passed = check.run_pass(conn, policy_loader.load(policy_path), poster, base_url)
            summary = f"inbox: {describe(report)}. check: {check.describe(passed)}"
            if summary != last or args.once:
                print(f"{db.now()} watch: {summary}", flush=True)
                last = summary
        except Exception:  # noqa: BLE001 - one bad pass must not stop the watcher
            traceback.print_exc()
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
