#!/usr/bin/env python3
"""Write each label PDF's text next to it, for a watcher that has no poppler. Standard library only.

    python3 scripts/pdf_pages.py ~/spraywatch-farm/inbox            # once
    python3 scripts/pdf_pages.py ~/spraywatch-farm/inbox --watch    # every POLL_SECONDS (default 5)

Runs on the host, where `pdftotext` is installed. The NemoClaw sandbox reads the
inbox read-only and has no poppler, so its watcher reads `<name>.pdf.pages.txt`
instead, and only if the sidecar's first line names the PDF's current SHA-256.
This step runs no model and reaches no network: it is `pdftotext -layout` and a
file write.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from labels import extract  # noqa: E402


def write_sidecars(inbox: Path) -> list[str]:
    """Every PDF in the inbox without a current sidecar gets one. Returns what it wrote or couldn't."""
    done = []
    for pdf in sorted(path for path in inbox.iterdir() if path.is_file() and path.suffix.lower() == ".pdf"):
        digest = extract.sha256(pdf)
        sidecar = extract.sidecar_path(pdf)
        try:
            extract.read_sidecar(pdf, digest)
            continue  # already current
        except extract.NotReady:
            pass
        try:
            text = extract.pdf_text(pdf)
        except extract.ExtractError as error:
            done.append(f"failed {pdf.name}: {error}")
            continue
        partial = sidecar.with_name(sidecar.name + ".part")
        partial.write_text(extract.sidecar_text(digest, text), encoding="utf-8")
        partial.replace(sidecar)  # whole or not at all: the watcher never sees half a sidecar
        done.append(f"wrote {sidecar.name}")
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("inbox", type=Path)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args(argv)
    interval = float(os.environ.get("POLL_SECONDS", "5"))
    while True:
        for line in write_sidecars(args.inbox):
            print(f"pdf_pages: {line}", flush=True)
        if not args.watch:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
