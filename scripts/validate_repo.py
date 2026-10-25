#!/usr/bin/env python3
"""Repository checks for SprayWatch, run by `make check`. Standard library only.

Fails on: missing required files, contract names that disappeared, tracked files
that must never be in git, and Markdown links to files that don't exist.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FILES = (
    ".gitignore",
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "contracts/README.md",
    "contracts/samples/label-reply.json",
    "contracts/samples/queue-change.json",
    "policy/policy.json",
    "docs/gb10.md",
    ".agents/lessons/README.md",
)

# Names the reader, the rules, the check and the page all rely on. Dropping one from
# the contract breaks them, so removing it has to be a deliberate change here too.
CONTRACT_TERMS = (
    "harvest_conflict",
    "entry_conflict",
    "unknown_product",
    "label_unconfirmed",
    "crop_not_on_label",
    "quote_verified",
    "label_facts",
    "crew_entries",
    "alerts",
    "events",
    "spraywatch.label/1",
    "spraywatch.queue/1",
)

# Never tracked, whatever .gitignore says: databases, label files, archives, keys.
# Real labels are public, but they stay out of git: scripts/fetch_labels.sh downloads them.
BANNED_SUFFIXES = (
    ".db", ".sqlite",
    ".pdf", ".png", ".jpg", ".jpeg",
    ".tar", ".tgz", ".xz",
    ".pem", ".key",
)

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout
    return [path for path in out.decode().split("\0") if path]


def check_required_files(errors: list[str]) -> None:
    for path in REQUIRED_FILES:
        if not (ROOT / path).is_file():
            errors.append(f"missing required file: {path}")


def check_contract_terms(errors: list[str]) -> None:
    contract = ROOT / "contracts" / "README.md"
    if not contract.is_file():
        return
    text = contract.read_text(encoding="utf-8")
    for term in CONTRACT_TERMS:
        if term not in text:
            errors.append(f"contracts/README.md no longer mentions: {term}")


def check_banned_files(errors: list[str], files: list[str]) -> None:
    for path in files:
        name = Path(path).name
        if path.lower().endswith(BANNED_SUFFIXES):
            errors.append(f"tracked file type that must stay out of git: {path}")
        elif name == ".env" or (name.startswith(".env.") and not name.endswith(".example")):
            errors.append(f"tracked environment file: {path}")


def check_markdown_links(errors: list[str], files: list[str]) -> None:
    for path in files:
        source = ROOT / path
        if not path.endswith(".md") or not source.is_file():
            continue
        text = FENCE.sub("", source.read_text(encoding="utf-8"))
        for target in LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target_path = target.split("#", 1)[0]
            if target_path and not (source.parent / target_path).exists():
                errors.append(f"{path}: broken link to {target}")


def main() -> int:
    errors: list[str] = []
    files = tracked_files()
    check_required_files(errors)
    check_contract_terms(errors)
    check_banned_files(errors, files)
    check_markdown_links(errors, files)
    for error in errors:
        print(f"validate_repo: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"validate_repo: {len(files)} tracked files OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
