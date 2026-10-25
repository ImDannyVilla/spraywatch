#!/usr/bin/env python3
"""Read policy/policy.json: approvers, times, crop aliases and the card templates. Standard library only.

`load()` checks every template uses only the contract's card fields, so a
template edit can't put a quote or a model note on a card. Run this file to
check policy.json by hand.
"""
from __future__ import annotations

import json
import re
import string
import sys
from pathlib import Path

POLICY = Path(__file__).resolve().parent / "policy.json"
SCHEMA = "spraywatch.policy/1"

# Each template and the placeholders it may use: the contract's card fields only.
CARD_FIELDS = {
    "harvest_conflict": {"block", "crop", "scheduled", "applied", "product", "product_type", "interval", "earliest"},
    "entry_conflict": {"block", "crop", "crew", "scheduled", "applied", "product", "product_type", "interval",
                       "earliest"},
    "unknown_product": {"block", "crop", "applied"},
    "label_unconfirmed": {"block", "crop", "applied", "product"},
    "crop_not_on_label": {"block", "crop", "applied", "product"},
    "spray": {"block", "crop", "product", "product_type", "applied_time", "rei_end"},
    "link": {"link"},
    "digest_header": {"date", "count", "plural"},
    "digest_none": {"date"},
    "digest_line": {"line", "link"},
}
TIME = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")


class PolicyError(ValueError):
    pass


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name is not None}


def validate(policy: dict) -> dict:
    if policy.get("schema") != SCHEMA:
        raise PolicyError(f"policy schema must be {SCHEMA}")
    approvers = policy.get("approvers")
    if not approvers or not all(isinstance(name, str) and name.strip() for name in approvers):
        raise PolicyError("policy needs at least one approver")
    for key in ("harvest_start_time", "morning_time"):
        if not isinstance(policy.get(key), str) or not TIME.fullmatch(policy[key]):
            raise PolicyError(f"{key} must be HH:MM")
    aliases = policy.get("crop_aliases", {})
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in aliases.items()):
        raise PolicyError("crop_aliases maps names to names")
    card = policy.get("card", {})
    missing = set(CARD_FIELDS) - set(card)
    if missing:
        raise PolicyError(f"card templates missing: {sorted(missing)}")
    for name, template in card.items():
        if name not in CARD_FIELDS:
            raise PolicyError(f"unknown card template: {name}")
        extra = placeholders(template) - CARD_FIELDS[name]
        if extra:
            raise PolicyError(f"card template {name} uses fields outside the contract: {sorted(extra)}")
    return policy


def load(path: Path | str = POLICY) -> dict:
    return validate(json.loads(Path(path).read_text(encoding="utf-8")))


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else POLICY
    try:
        load(target)
    except (PolicyError, ValueError) as error:
        print(f"policy: {error}", file=sys.stderr)
        sys.exit(1)
    print(f"policy: {target} OK")
