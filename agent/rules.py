"""The PHI and REI rules, exactly as contracts/README.md "The rules" says. Standard library only.

Pure functions over plain records: no SQLite, no model, no clock. `evaluate`
takes the farm's state and today's date and returns every finding; the check
pass (`agent/check.py`) turns findings into alerts.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

# Label problems are raised for sprays this recent, or with a planned harvest or entry after them.
LOOKBACK_DAYS = 30


@dataclass(frozen=True)
class Block:
    block_id: str
    name: str
    crop: str


@dataclass(frozen=True)
class Fact:
    crop: str  # "*" for the general REI
    kind: str  # "phi" or "rei"
    hours: float
    fact_id: int | None = None


@dataclass(frozen=True)
class Label:
    label_id: int
    product_name: str
    epa_reg_no: str | None
    product_type: str
    state: str
    facts: tuple[Fact, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Spray:
    spray_id: int
    block_id: str
    product: str
    epa_reg_no: str | None
    applied_at: datetime


@dataclass(frozen=True)
class Harvest:
    harvest_id: str
    block_id: str
    planned_date: date


@dataclass(frozen=True)
class Entry:
    entry_id: str
    block_id: str
    crew: str
    planned_at: datetime


@dataclass(frozen=True)
class Finding:
    kind: str
    block_id: str
    spray_id: int | None = None
    label_id: int | None = None
    harvest_id: str | None = None
    entry_id: str | None = None
    scheduled: str | None = None
    earliest: str | None = None
    reason: str | None = None  # "phi" or "rei" for conflicts
    interval_hours: float | None = None

    @property
    def key(self) -> str:
        """Names the conflict exactly: the same conflict gets the same key, a changed one a new key."""
        if self.kind == "harvest_conflict":
            return f"harvest:{self.harvest_id}:{self.scheduled}:{self.earliest}:{self.spray_id}"
        if self.kind == "entry_conflict":
            return f"entry:{self.entry_id}:{self.scheduled}:{self.earliest}:{self.spray_id}"
        return f"{self.kind}:{self.spray_id}:{self.label_id if self.label_id is not None else '-'}"


# Parsing and matching -------------------------------------------------------------------------

def parse_date(value: str) -> date:
    return date.fromisoformat(value.strip())


def parse_datetime(value: str) -> datetime:
    """`YYYY-MM-DDTHH:MM` (a space works too). Farm-local, no offset."""
    text = value.strip().replace(" ", "T")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        raise ValueError("times are farm-local, without an offset")
    return parsed


def fmt_date(value: date) -> str:
    return value.isoformat()


def fmt_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M")


def crop_key(crop: str, aliases: dict[str, str]) -> str:
    text = " ".join(crop.lower().split())
    return aliases.get(text, text)


def product_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def reg_key(reg: str | None) -> str | None:
    if not reg:
        return None
    return re.sub(r"[^0-9-]", "", reg).strip("-") or None


def match_label(spray: Spray, labels: list[Label]) -> tuple[Label | None, str]:
    """The spray's label and how it stands: `confirmed`, `unconfirmed` or `none`.

    EPA registration number first, then the product name. Rejected labels never match.
    """
    live = [label for label in labels if label.state != "rejected"]
    reg = reg_key(spray.epa_reg_no)
    matches = [label for label in live if reg and reg_key(label.epa_reg_no) == reg]
    if not matches:
        matches = [label for label in live if product_key(label.product_name) == product_key(spray.product)]
    if not matches:
        return None, "none"
    confirmed = [label for label in matches if label.state == "confirmed"]
    if confirmed:
        return max(confirmed, key=lambda label: label.label_id), "confirmed"
    return max(matches, key=lambda label: label.label_id), "unconfirmed"


def intervals(label: Label, crop: str, aliases: dict[str, str]) -> tuple[int, float] | None:
    """(PHI in days, REI in hours) for the crop, or None if the label doesn't list the crop.

    The per-crop REI wins over the general one (rule 3).
    """
    wanted = crop_key(crop, aliases)
    phi = [fact for fact in label.facts if fact.kind == "phi" and crop_key(fact.crop, aliases) == wanted]
    if not phi:
        return None
    rei = [fact for fact in label.facts if fact.kind == "rei" and crop_key(fact.crop, aliases) == wanted]
    if not rei:
        rei = [fact for fact in label.facts if fact.kind == "rei" and fact.crop == "*"]
    if not rei:
        return None
    # Two readings of the same limit: keep the stricter one.
    phi_days = max(math.ceil(fact.hours / 24 - 1e-9) for fact in phi)
    rei_hours = max(fact.hours for fact in rei)
    return phi_days, rei_hours


# The rules -------------------------------------------------------------------------------------

def earliest_harvest(spray: Spray, phi_days: int, rei_hours: float, start: time) -> tuple[date, str]:
    """The earliest legal harvest date after one spray (rules 1 and 2), and which interval binds."""
    phi_date = spray.applied_at.date() + timedelta(days=phi_days)
    rei_end = spray.applied_at + timedelta(hours=rei_hours)
    rei_date = rei_end.date() if rei_end.time() <= start else rei_end.date() + timedelta(days=1)
    if phi_date >= rei_date:
        return phi_date, "phi"
    return rei_date, "rei"


def earliest_entry(spray: Spray, rei_hours: float) -> datetime:
    return spray.applied_at + timedelta(hours=rei_hours)


def evaluate(blocks: list[Block], sprays: list[Spray], labels: list[Label], harvests: list[Harvest],
             entries: list[Entry], policy: dict, today: date) -> list[Finding]:
    aliases = {crop_key(k, {}): crop_key(v, {}) for k, v in policy.get("crop_aliases", {}).items()}
    start = time.fromisoformat(policy["harvest_start_time"])
    by_block = {block.block_id: block for block in blocks}
    harvests = [h for h in harvests if h.planned_date >= today]
    start_of_today = datetime.combine(today, time(0, 0))
    entries = [e for e in entries if e.planned_at >= start_of_today]
    findings: list[Finding] = []

    # Each spray's label and intervals; label problems become findings (rule 6).
    usable: dict[int, tuple[Spray, Label, int, float]] = {}
    for spray in sorted(sprays, key=lambda s: (s.applied_at, s.spray_id)):
        block = by_block.get(spray.block_id)
        if block is None:
            continue
        label, standing = match_label(spray, labels)
        later = any(h.block_id == spray.block_id and datetime.combine(h.planned_date, start) > spray.applied_at
                    for h in harvests) or any(
            e.block_id == spray.block_id and e.planned_at > spray.applied_at for e in entries)
        recent = spray.applied_at.date() >= today - timedelta(days=LOOKBACK_DAYS)
        applied = fmt_datetime(spray.applied_at)
        if standing == "none":
            if later or recent:
                findings.append(Finding("unknown_product", block.block_id, spray.spray_id, scheduled=applied))
            continue
        if standing == "unconfirmed":
            if later or recent:
                findings.append(Finding("label_unconfirmed", block.block_id, spray.spray_id, label.label_id,
                                        scheduled=applied))
            continue
        limits = intervals(label, block.crop, aliases)
        if limits is None:
            if later or recent:
                findings.append(Finding("crop_not_on_label", block.block_id, spray.spray_id, label.label_id,
                                        scheduled=applied))
            continue
        usable[spray.spray_id] = (spray, label, *limits)

    # Rules 1, 2, 4, 7 for every planned harvest.
    for harvest in sorted(harvests, key=lambda h: (h.planned_date, h.harvest_id)):
        harvest_start = datetime.combine(harvest.planned_date, start)
        worst = None
        for spray, label, phi_days, rei_hours in usable.values():
            if spray.block_id != harvest.block_id or spray.applied_at >= harvest_start:
                continue
            earliest, reason = earliest_harvest(spray, phi_days, rei_hours, start)
            candidate = (earliest, spray.applied_at, spray.spray_id, label.label_id, reason,
                         phi_days * 24.0 if reason == "phi" else rei_hours)
            if worst is None or candidate[:3] > worst[:3]:
                worst = candidate
        if worst and harvest.planned_date < worst[0]:
            earliest, _, spray_id, label_id, reason, hours = worst
            findings.append(Finding("harvest_conflict", harvest.block_id, spray_id, label_id,
                                    harvest_id=harvest.harvest_id, scheduled=fmt_date(harvest.planned_date),
                                    earliest=fmt_date(earliest), reason=reason, interval_hours=hours))

    # Rules 2, 4, 7 for every planned crew entry.
    for entry in sorted(entries, key=lambda e: (e.planned_at, e.entry_id)):
        worst = None
        for spray, label, _, rei_hours in usable.values():
            if spray.block_id != entry.block_id or spray.applied_at >= entry.planned_at:
                continue
            candidate = (earliest_entry(spray, rei_hours), spray.applied_at, spray.spray_id, label.label_id,
                         rei_hours)
            if worst is None or candidate[:3] > worst[:3]:
                worst = candidate
        if worst and entry.planned_at < worst[0]:
            earliest, _, spray_id, label_id, hours = worst
            findings.append(Finding("entry_conflict", entry.block_id, spray_id, label_id, entry_id=entry.entry_id,
                                    scheduled=fmt_datetime(entry.planned_at), earliest=fmt_datetime(earliest),
                                    reason="rei", interval_hours=hours))
    return findings
