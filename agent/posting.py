"""The do-not-enter posting, in English and Spanish, from fixed wording. Standard library only.

Code fills the block, product, application time and REI end from SQLite; the
words around them are fixed here, so no model text and no machine translation
ends up on a sign. The headline follows the Worker Protection Standard's sign
(DANGER / PELIGRO, PESTICIDES / PESTICIDAS, KEEP OUT / NO ENTRE). Whether a
sign is required is for the label and the WPS; the manager decides.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from agent import rules, store

DAYS_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MONTHS_ES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
             "noviembre", "diciembre")


class PostingError(ValueError):
    pass


@dataclass(frozen=True)
class Posting:
    spray_id: int
    block: str
    product: str
    epa_reg_no: str | None
    headline_en: tuple[str, ...]
    headline_es: tuple[str, ...]
    body_en: str
    body_es: str
    rei_end: datetime


def when_en(value: datetime) -> str:
    hour = value.strftime("%I:%M %p").lstrip("0")
    return f"{value:%A, %B} {value.day} at {hour}"


def when_es(value: datetime) -> str:
    return f"{DAYS_ES[value.weekday()]} {value.day} de {MONTHS_ES[value.month - 1]} a las {value:%H:%M}"


def hours_en(hours: float) -> str:
    if hours >= 72 and hours % 24 == 0:
        return f"{hours / 24:g} days"
    return f"{hours:g} hours"


def hours_es(hours: float) -> str:
    if hours >= 72 and hours % 24 == 0:
        return f"{hours / 24:g} días"
    return f"{hours:g} horas"


def build(conn: sqlite3.Connection, policy: dict, spray_id: int) -> Posting:
    """The posting for one spray. Needs a confirmed label that lists the block's crop."""
    spray_row = conn.execute("SELECT * FROM sprays WHERE spray_id = ?", (spray_id,)).fetchone()
    if spray_row is None:
        raise PostingError("no such spray")
    state = store.load_state(conn)
    spray = next(s for s in state["sprays"] if s.spray_id == spray_id)
    block = next(b for b in state["blocks"] if b.block_id == spray.block_id)
    label, standing = rules.match_label(spray, state["labels"])
    if standing != "confirmed":
        raise PostingError("the product's label isn't confirmed yet, so the restricted-entry interval isn't known")
    aliases = {rules.crop_key(k, {}): rules.crop_key(v, {}) for k, v in policy.get("crop_aliases", {}).items()}
    limits = rules.intervals(label, block.crop, aliases)
    if limits is None:
        raise PostingError("the label doesn't list this block's crop")
    rei_hours = limits[1]
    rei_end = rules.earliest_entry(spray, rei_hours)
    body_en = (f"{block.name} was treated with {label.product_name} on {when_en(spray.applied_at)}. "
               f"Do not enter until {when_en(rei_end)}. Restricted-entry interval: {hours_en(rei_hours)}.")
    body_es = (f"{block.name} fue tratado con {label.product_name} el {when_es(spray.applied_at)}. "
               f"No entre hasta el {when_es(rei_end)}. Intervalo de entrada restringida: {hours_es(rei_hours)}.")
    return Posting(spray_id, block.name, label.product_name, label.epa_reg_no,
                   ("DANGER", "PESTICIDES", "KEEP OUT"), ("PELIGRO", "PESTICIDAS", "NO ENTRE"),
                   body_en, body_es, rei_end)
