"""Slack cards, built by code from the policy's fixed templates. Standard library only.

Only the contract's card fields reach a card: block name, crop, the confirmed
product name and type, dates and times, the interval, the crew name and the
local page's link. Every builder checks its fields, so a label quote, a model
note or a file name can't be passed in by mistake.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime

from agent import rules
from labels import reader

LINK = re.compile(r"http://127\.0\.0\.1:[0-9]+/(?:alert|spray|posting|label)/[0-9]+")
PLAIN = re.compile(r"[A-Za-z0-9 \-.,%/()®™&+'#:_]{1,80}")


class CardError(ValueError):
    """A card was asked to carry something outside the contract's fields."""


def slack_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def plain(value, what: str) -> str:
    text = " ".join(str(value or "").split())
    if not PLAIN.fullmatch(text):
        raise CardError(f"{what} isn't plain text a card may carry")
    return slack_escape(text)


def product(value: str) -> str:
    if not reader.PRODUCT_NAME.fullmatch(value or ""):
        raise CardError("not a product name")
    return slack_escape(value)


def product_type(value: str) -> str:
    if value not in reader.PRODUCT_TYPES:
        raise CardError(f"not a product type: {value!r}")
    return value


def link(value: str) -> str:
    if not LINK.fullmatch(value):
        raise CardError("the link must be the local page on 127.0.0.1")
    return value


def day(value: date) -> str:
    """'Thursday Oct 29'."""
    return f"{value:%A %b} {value.day}"


def moment(value: datetime) -> str:
    """'Tuesday Oct 27 07:30'."""
    return f"{day(value.date())} {value:%H:%M}"


def interval(hours: float, reason: str) -> str:
    """'7 days' for a PHI; '24 hours' or '3 days' for an REI, as the label most likely says it."""
    if reason == "phi" or (hours >= 72 and hours % 24 == 0):
        days = round(hours / 24)
        return f"{days} day{'s' if days != 1 else ''}"
    value = f"{hours:g}"
    return f"{value} hour{'s' if hours != 1 else ''}"


def with_link(policy: dict, text: str, url: str) -> str:
    return text + "\n" + policy["card"]["link"].format(link=link(url))


# From SQLite ---------------------------------------------------------------------------------

def alert_context(conn: sqlite3.Connection, alert_id: int) -> dict:
    alert = conn.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
    if alert is None:
        raise KeyError(f"no such alert: {alert_id}")
    block = conn.execute("SELECT * FROM blocks WHERE block_id = ?", (alert["block_id"],)).fetchone()
    spray = conn.execute("SELECT * FROM sprays WHERE spray_id = ?", (alert["spray_id"],)).fetchone()
    label = (conn.execute("SELECT * FROM labels WHERE label_id = ?", (alert["label_id"],)).fetchone()
             if alert["label_id"] is not None else None)
    entry = (conn.execute("SELECT * FROM crew_entries WHERE entry_id = ?", (alert["entry_id"],)).fetchone()
             if alert["entry_id"] else None)
    return {"alert": alert, "block": block, "spray": spray, "label": label, "entry": entry}


def alert_line(policy: dict, context: dict) -> str:
    """The alert's one-line summary: the card's first line and the digest's line."""
    alert, block, spray, label = context["alert"], context["block"], context["spray"], context["label"]
    kind = alert["kind"]
    template = policy["card"][kind]
    fields = {"block": plain(block["name"], "block name"), "crop": plain(block["crop"], "crop"),
              "applied": day(rules.parse_datetime(spray["applied_at"]).date())}
    if kind in ("label_unconfirmed", "crop_not_on_label"):
        # An unconfirmed label's name is the spray log's, typed by a person, not the model's.
        fields["product"] = plain(spray["product"], "product") if kind == "label_unconfirmed" else product(
            label["product_name"])
    if kind in ("harvest_conflict", "entry_conflict"):
        if label["state"] != "confirmed":
            raise CardError("a conflict card needs a confirmed label")
        fields.update(product=product(label["product_name"]), product_type=product_type(label["product_type"]),
                      interval=interval(alert["interval_hours"], alert["reason"]))
        if kind == "harvest_conflict":
            fields.update(scheduled=day(rules.parse_date(alert["scheduled"])),
                          earliest=day(rules.parse_date(alert["earliest"])))
        else:
            fields.update(crew=plain(context["entry"]["crew"], "crew"),
                          scheduled=moment(rules.parse_datetime(alert["scheduled"])),
                          earliest=moment(rules.parse_datetime(alert["earliest"])))
    return template.format(**fields)


def alert_card(conn: sqlite3.Connection, policy: dict, alert_id: int, base_url: str) -> str:
    context = alert_context(conn, alert_id)
    return with_link(policy, alert_line(policy, context), f"{base_url.rstrip('/')}/alert/{alert_id}")


def spray_card(conn: sqlite3.Connection, policy: dict, spray_id: int, rei_end: datetime, label_id: int,
               base_url: str) -> str:
    spray = conn.execute("SELECT * FROM sprays WHERE spray_id = ?", (spray_id,)).fetchone()
    block = conn.execute("SELECT * FROM blocks WHERE block_id = ?", (spray["block_id"],)).fetchone()
    label = conn.execute("SELECT * FROM labels WHERE label_id = ?", (label_id,)).fetchone()
    if label["state"] != "confirmed":
        raise CardError("a spray card needs a confirmed label")
    text = policy["card"]["spray"].format(
        block=plain(block["name"], "block name"), crop=plain(block["crop"], "crop"),
        product=product(label["product_name"]), product_type=product_type(label["product_type"]),
        applied_time=moment(rules.parse_datetime(spray["applied_at"])), rei_end=moment(rei_end))
    return with_link(policy, text, f"{base_url.rstrip('/')}/posting/{spray_id}")


def digest_card(conn: sqlite3.Connection, policy: dict, today: date, alert_ids: list[int], base_url: str) -> str:
    """Every open alert, one line each with its link, or the no-alerts line."""
    card = policy["card"]
    if not alert_ids:
        return card["digest_none"].format(date=day(today))
    count = len(alert_ids)
    lines = [card["digest_header"].format(date=day(today), count=count, plural="" if count == 1 else "s")]
    for alert_id in alert_ids:
        lines.append(card["digest_line"].format(line=alert_line(policy, alert_context(conn, alert_id)),
                                                link=link(f"{base_url.rstrip('/')}/alert/{alert_id}")))
    return "\n".join(lines)
