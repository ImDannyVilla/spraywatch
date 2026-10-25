#!/usr/bin/env python3
"""Build the demo farm with today's dates, read its labels, and run the check. Standard library only.

    python3 scripts/demo.py                 # fake model replies, cards printed
    python3 scripts/demo.py --live          # the real model (SPRAYWATCH_MODEL_ENV or MODEL_*)
    python3 scripts/demo.py --no-confirm    # leave the labels for the manager to confirm on the page

The farm, in `state/demo/` (removed and rebuilt each run):

| Block | Crop | What happens |
| --- | --- | --- |
| Block 4 | grapes | Yesterday's DEMOFUNG 50 WP needs 7 days; harvest is set for 3 days after it: harvest alert |
| Block 5 | grapes | Yesterday's DEMOTHRIN 2EC keeps grapes closed 3 days; Crew A goes in tomorrow: entry alert |
| Block 1 | strawberries | Yesterday evening's Captan 80 DF (or DEMOFUNG without the real label), harvest tomorrow: clean |
| Block 7 | lettuce | A product with no label on file: unknown-product alert |

The real Captan label is used when `scripts/fetch_labels.sh` has downloaded it.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import approval, check, db, slack, watch  # noqa: E402
from policy import policy as policy_loader  # noqa: E402
from scripts import make_pdf  # noqa: E402

DEMO = ROOT / "demo"
REAL_LABELS = ROOT / "state" / "labels"


def write(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_inbox(inbox: Path, today: date) -> bool:
    """The demo inbox. Returns whether the real Captan label is in it."""
    inbox.mkdir(parents=True)
    for label in sorted((DEMO / "labels").glob("*.txt")):
        if shutil.which("pdftotext"):
            (inbox / f"{label.stem}.pdf").write_bytes(make_pdf.pdf_bytes(label.read_text(encoding="utf-8")))
        else:
            shutil.copy(label, inbox)
    captan = REAL_LABELS / "captan-80-df.pdf"
    real = captan.is_file() and shutil.which("pdftotext") is not None
    if real:
        shutil.copy(captan, inbox)
    yesterday, tomorrow = today - timedelta(days=1), today + timedelta(days=1)
    write(inbox / "blocks.csv", "block_id,name,crop,acres",
          "B1,Block 1,strawberries,4.5", "B4,Block 4,grapes,12", "B5,Block 5,grapes,8", "B7,Block 7,lettuce,3")
    write(inbox / "harvests.csv", "harvest_id,block_id,planned_date",
          f"H4,B4,{yesterday + timedelta(days=3)}", f"H1,B1,{tomorrow}")
    write(inbox / "crew.csv", "entry_id,block_id,crew,task,planned_at",
          f"E5,B5,Crew A,cane turning,{tomorrow}T07:00")
    berries = "Captan 80 DF,42750-231" if real else "Demofung 50 WP,99999-101"
    write(inbox / "sprays.csv", "block_id,product,epa_reg_no,applied_at,applicator",
          f"B4,Demofung 50 WP,99999-101,{yesterday}T08:00,J. Ruiz",
          f"B5,Demothrin 2EC,99999-202,{yesterday}T07:00,J. Ruiz",
          f"B1,{berries},{yesterday}T17:00,M. Chen",
          f"B7,Leaf Shine Oil,,{yesterday}T15:00,M. Chen")
    return real


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--live", action="store_true", help="read the labels with the real model")
    parser.add_argument("--no-confirm", action="store_true", help="leave the labels for the page")
    parser.add_argument("--state", type=Path, default=ROOT / "state" / "demo")
    args = parser.parse_args(argv)

    state = args.state
    if state.exists():
        shutil.rmtree(state)
    inbox = state / "inbox"
    now = datetime.now().replace(second=0, microsecond=0)
    real = build_inbox(inbox, now.date())
    conn = db.connect(state / "spraywatch.db")
    policy = policy_loader.load()
    if args.live:
        env_file = os.environ.get("SPRAYWATCH_MODEL_ENV")
        models = watch.ModelSource(env_file=Path(env_file) if env_file else None)
    else:
        models = watch.ModelSource(fake_replies=DEMO / "replies")
    print(f"demo: reading the inbox ({'real model' if args.live else 'fake replies'}; "
          f"real Captan label {'in' if real else 'not fetched: run scripts/fetch_labels.sh'})")
    report = watch.scan(conn, inbox, models)
    print(f"demo: {watch.describe(report)}")
    if report.failed:
        return 1
    if not args.no_confirm:
        for row in conn.execute("SELECT label_id FROM labels WHERE state = 'extracted'").fetchall():
            approval.confirm_label(conn, policy, row["label_id"], policy["approvers"][0])
        print(f"demo: labels confirmed as {policy['approvers'][0]} (use --no-confirm to do it on the page)")
    poster = slack.poster_from_env()
    if poster is slack.unconfigured_poster:
        poster = slack.print_poster
    passed = check.run_pass(conn, policy, poster, now=now, force_digest=True)
    print(f"demo: check: {check.describe(passed)}")
    print("\nOpen the page:\n"
          f"  SPRAYWATCH_DB={state / 'spraywatch.db'} SPRAYWATCH_INBOX={inbox} SPRAYWATCH_QUEUE={state / 'queue'} "
          "SPRAYWATCH_SLACK=print python3 evidence/server.py\n  http://127.0.0.1:8091/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
