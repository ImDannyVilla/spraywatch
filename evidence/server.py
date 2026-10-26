#!/usr/bin/env python3
"""The local page. Standard library only.

    python3 evidence/server.py      # http://127.0.0.1:8091/

Pages, as contracts/README.md "The local page" says:

- `/`: open alerts, labels waiting for a person, blocks, the schedule and recent sprays.
- `/alert/<id>`: the conflict, the rule's arithmetic, the binding spray, the
  label line as proof, and Approve.
- `/label/<id>`: every fact with its quote and the label page around it, Confirm and Reject.
- `/spray/new`: log a spray; the check runs at once, so the card goes out now.
- `/posting/<spray_id>`: the do-not-enter posting in English and Spanish, ready to print.

Only the GB10's own browser can reach it: it binds to 127.0.0.1, POSTs carry a
per-run form token, and the Host header must be the loopback address, so
another web page open in the same browser can't press the buttons.
"""
from __future__ import annotations

import html
import json
import os
import secrets
import sqlite3
import sys
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import approval, card, check, db, posting, rules, slack, store  # noqa: E402
from policy import policy as policy_loader  # noqa: E402

MAX_FORM_BYTES = 16 * 1024
EXCERPT_LINES = 3


@dataclass
class Config:
    db_path: Path = db.DEFAULT_DB
    policy_path: Path = policy_loader.POLICY
    queue_dir: Path = approval.DEFAULT_QUEUE
    inbox_dir: Path = ROOT / "state" / "inbox"
    host: str = "127.0.0.1"
    port: int = 8091
    poster: slack.Poster = slack.unconfigured_poster
    clock: Callable[[], datetime] = lambda: datetime.now().replace(second=0, microsecond=0)
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @classmethod
    def from_env(cls) -> "Config":
        env = os.environ.get
        return cls(
            db_path=Path(env("SPRAYWATCH_DB", str(db.DEFAULT_DB))),
            policy_path=Path(env("SPRAYWATCH_POLICY", str(policy_loader.POLICY))),
            queue_dir=Path(env("SPRAYWATCH_QUEUE", str(approval.DEFAULT_QUEUE))),
            inbox_dir=Path(env("SPRAYWATCH_INBOX", str(ROOT / "state" / "inbox"))),
            host=env("PAGE_HOST", "127.0.0.1"),
            port=int(env("PAGE_PORT", "8091")),
            poster=slack.poster_from_env(),
        )


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def unslack(text: str) -> str:
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


# The look follows the PS4 20th Anniversary theme: a flat grey ground with a faint pattern of the four
# PlayStation shapes, flat light tiles, and pictograms banded in the four stripe colours.
CSS = """
:root{--bg:#c9cacc;--tile:#f2f2f2;--tile2:#e6e6e6;--ink:#222;--muted:#5d5d5d;--line:#dddddd;
--red:#e2231a;--yellow:#f6be00;--green:#00a650;--blue:#0072ce}
html{background:var(--bg)}
.ground{position:fixed;top:0;left:0;width:100%;height:100%;z-index:-1}
body{font-family:"SST","Helvetica Neue",Helvetica,Ubuntu,Arial,sans-serif;margin:0 auto;max-width:1100px;
padding:1.5rem 1.25rem 3rem;color:var(--ink);line-height:1.45}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
a:focus,button:focus,select:focus,input:focus{outline:3px solid var(--blue);outline-offset:2px}
header.top{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem 1.5rem;margin-bottom:1.5rem}
header.top .brand{display:flex;align-items:center;gap:.6rem;color:var(--ink);font-size:1.45rem;font-weight:300}
header.top .brand svg{width:22px;height:22px}
header.top nav a{color:var(--ink)}
header.top .note{margin-left:auto;color:var(--muted);font-size:.85rem}
h1{font-size:2.1rem;font-weight:300;margin:.2rem 0 1rem}
h2{font-size:1.05rem;font-weight:400;color:#3a3a3a;margin:2rem 0 .6rem}
.tiles{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:6px}
.tile{background:var(--tile);padding:1.1rem 1.1rem 1.2rem;min-height:190px}
.tile .icon{width:64px;height:64px;display:block;margin-bottom:.9rem}
.tile p{margin:0}.tile .tile-id{margin-bottom:.3rem;font-size:.85rem}
table{border-collapse:collapse;width:100%;background:var(--tile)}
th,td{text-align:left;padding:.55rem .8rem;border-bottom:1px solid var(--line);vertical-align:top}
th{font-weight:600;font-size:.85rem;color:var(--muted)}tr:last-child td{border-bottom:0}
.wrap{overflow-x:auto}
.tag{display:inline-block;padding:.05rem .45rem;border-radius:2px;font-weight:600;font-size:.78rem;
background:var(--tile2);color:var(--ink);vertical-align:middle}
.tag-open,.tag-unverified,.tag-extracted{background:var(--yellow)}
.tag-approved,.tag-confirmed,.tag-verified{background:var(--green);color:#fff}
.tag-rejected{background:var(--red);color:#fff}.tag-resolved{color:var(--muted)}
.card,main>form{background:var(--tile);padding:1rem 1.2rem;margin:6px 0}
.banner{padding:.7rem 1rem;margin:.6rem 0;font-weight:600;background:var(--tile)}
.banner-ok{color:#006b33}.banner-refused{color:#b3170f}
pre.label{background:#fafafa;padding:.6rem .8rem;overflow-x:auto;white-space:pre-wrap;font-size:.85rem;margin:.5rem 0 0}
pre.label mark{background:rgba(246,190,0,.45);color:inherit;display:block}
.quote{margin:.4rem 0;color:#444;font-style:italic}
button{font:inherit;font-size:.95rem;padding:.5rem 1.1rem;margin:.3rem .5rem .3rem 0;cursor:pointer;
background:var(--blue);color:#fff;border:0;border-radius:2px}
button:hover{background:#005fae}
label{margin-right:.4rem}
input,select{font:inherit;font-size:.95rem;margin:.2rem .6rem .2rem 0;padding:.35rem .5rem;border:1px solid #bdbdbd;
border-radius:2px;background:#fff}
.muted{color:var(--muted)}
.sign{background:#fff;color:#111;border:6px solid #111;padding:1rem 1.5rem;margin:1rem 0;page-break-inside:avoid}
.sign .head{font-size:2.6rem;font-weight:800;line-height:1.1;margin:0 0 .6rem}
.sign p{font-size:1.25rem}
@media print{html{background:none}.ground,header,.noprint{display:none}body{max-width:none;padding:0}}
"""

# The four stripe colours, top to bottom, as hard bands any pictogram can fill with, and the faint
# pattern of the four PlayStation shapes behind the page. Both are inline SVG: the page's
# Content-Security-Policy allows no data: images.
BANDS = ("<svg width=\"0\" height=\"0\" style=\"position:absolute\" aria-hidden=\"true\" focusable=\"false\"><defs>"
         "<linearGradient id=\"ps-bands\" x1=\"0\" y1=\"0\" x2=\"0\" y2=\"1\">"
         "<stop offset=\"0\" stop-color=\"#e2231a\"/><stop offset=\".25\" stop-color=\"#e2231a\"/>"
         "<stop offset=\".25\" stop-color=\"#f6be00\"/><stop offset=\".5\" stop-color=\"#f6be00\"/>"
         "<stop offset=\".5\" stop-color=\"#00a650\"/><stop offset=\".75\" stop-color=\"#00a650\"/>"
         "<stop offset=\".75\" stop-color=\"#0072ce\"/><stop offset=\"1\" stop-color=\"#0072ce\"/>"
         "</linearGradient>"
         "<pattern id=\"ps-shapes\" width=\"160\" height=\"160\" patternUnits=\"userSpaceOnUse\">"
         "<g fill=\"none\" stroke=\"#fff\" stroke-opacity=\".5\" stroke-width=\"1.5\">"
         "<path d=\"M24 14l8 14h-16z\"/><circle cx=\"104\" cy=\"26\" r=\"7\"/>"
         "<path d=\"M57 92l12 12m0-12l-12 12\"/><rect x=\"128\" y=\"112\" width=\"12\" height=\"12\"/></g>"
         "</pattern></defs></svg>"
         "<svg class=\"ground\" aria-hidden=\"true\" focusable=\"false\">"
         "<rect width=\"100%\" height=\"100%\" fill=\"url(#ps-shapes)\"/></svg>")

# One pictogram per alert kind, on a 64 x 64 grid; holes are cut with the even-odd rule.
ICONS = {
    "harvest_conflict": ("M16 4h6v8h-6zM42 4h6v8h-6zM6 12h52v46H6zM12 24h10v10H12zM28 24h10v10H28z"
                         "M44 24h10v10H44zM12 40h10v10H12zM28 40h10v10H28zM44 40h10v10H44z"),  # a calendar
    "entry_conflict": ("M6 10h52v10H6zM6 50h52v8H6zM10 20h6v30h-6zM22 20h6v30h-6zM34 20h6v30h-6z"
                       "M46 20h6v30h-6z"),  # a gate
    "label": "M8 14h32l16 18-16 18H8zM20 32a4 4 0 1 0 8 0a4 4 0 1 0-8 0z",  # a tag: the label itself
}


def icon(kind: str) -> str:
    path = ICONS.get(kind, ICONS["label"])
    return ("<svg class=\"icon\" viewBox=\"0 0 64 64\" aria-hidden=\"true\" focusable=\"false\">"
            f"<path fill=\"url(#ps-bands)\" fill-rule=\"evenodd\" d=\"{path}\"/></svg>")


def page(title: str, body: str) -> str:
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{esc(title)} · SprayWatch</title><style>{CSS}</style></head><body>{BANDS}"
            "<header class=\"top noprint\"><a class=\"brand\" href=\"/\"><svg viewBox=\"0 0 4 4\" aria-hidden=\"true\">"
            "<rect width=\"4\" height=\"4\" fill=\"url(#ps-bands)\"/></svg>SprayWatch</a>"
            "<nav><a href=\"/spray/new\">Log a spray</a></nav>"
            "<span class=\"note\">local page, on this machine only</span></header>"
            f"<main>{body}</main></body></html>")


def tag(state: str) -> str:
    return f"<span class=\"tag tag-{esc(state)}\">{esc(state.replace('_', ' '))}</span>"


def banner(query: dict) -> str:
    if "refused" in query:
        return f"<div class=\"banner banner-refused\" role=\"alert\">Refused: {esc(query['refused'])}</div>"
    if "done" in query:
        return f"<div class=\"banner banner-ok\" role=\"status\">{esc(query['done'])}</div>"
    return ""


def form(config: Config, action: str, hidden: dict, inner: str, label: str) -> str:
    fields = "".join(f"<input type=\"hidden\" name=\"{esc(k)}\" value=\"{esc(v)}\">" for k, v in hidden.items())
    return (f"<form method=\"post\" action=\"/action/{esc(action)}\">"
            f"<input type=\"hidden\" name=\"token\" value=\"{esc(config.token)}\">{fields}{inner}"
            f"<button type=\"submit\">{esc(label)}</button></form>")


def approver_select(policy: dict, name_id: str) -> str:
    options = "".join(f"<option>{esc(name)}</option>" for name in policy["approvers"])
    return (f"<label for=\"{name_id}\">Approver</label>"
            f"<select id=\"{name_id}\" name=\"approver\" required>{options}</select>")


def label_excerpt(label: sqlite3.Row, page_number: int | None, line: int | None) -> str:
    """The label page around the cited line, with the line marked: the proof."""
    pages = json.loads(label["pages_json"])
    if not pages:
        return "<p class=\"muted\">This label is a photo: compare the quote with the photo itself.</p>"
    if not page_number or not 1 <= page_number <= len(pages):
        return "<p class=\"muted\">The cited page isn't in the label.</p>"
    lines = pages[page_number - 1]
    line = line or 1
    first, last = max(1, line - EXCERPT_LINES), min(len(lines), line + EXCERPT_LINES)
    out = []
    for number in range(first, last + 1):
        text = esc(f"L{number:<4} {lines[number - 1]}")
        out.append(f"<mark>{text}</mark>" if number == line else text)
    return (f"<p class=\"muted\">{esc(label['source_file'])}, page {page_number}, lines {first} to {last}:</p>"
            f"<pre class=\"label\" aria-label=\"Label text around line {line}\">" + "\n".join(out) + "</pre>")


def fact_block(label: sqlite3.Row, fact: sqlite3.Row) -> str:
    verified = "verified" if fact["quote_verified"] else "unverified"
    what = ("Pre-harvest interval" if fact["kind"] == "phi" else "Restricted-entry interval")
    crop = "all crops (general)" if fact["crop"] == "*" else fact["crop"]
    if fact["condition"]:
        crop += f" ({fact['condition']})"
    value = f"{fact['value']:g} {fact['unit']}"
    return (f"<div class=\"card\"><p><strong>{esc(what)}</strong>, {esc(crop)}: <strong>{esc(value)}</strong> "
            f"{tag(verified)}</p><p class=\"quote\">“{esc(fact['quote'])}”</p>"
            f"{label_excerpt(label, fact['page'], fact['line'])}</div>")


# Pages -------------------------------------------------------------------------------------

def render_index(conn: sqlite3.Connection, config: Config, policy: dict, query: dict) -> str:
    body = [f"<h1>{esc(policy.get('farm_name', 'SprayWatch'))}</h1>", banner(query)]
    alerts = conn.execute("SELECT alert_id, kind FROM alerts WHERE state = 'open' ORDER BY alert_id").fetchall()
    body.append(f"<h2>Open alerts ({len(alerts)})</h2>")
    if alerts:
        items = []
        for row in alerts:
            try:
                line = unslack(card.alert_line(policy, card.alert_context(conn, row["alert_id"])))
            except card.CardError as error:
                line = f"(can't summarize: {error})"
            items.append(f"<li class=\"tile\">{icon(row['kind'])}<p class=\"tile-id\">"
                         f"<a href=\"/alert/{row['alert_id']}\">Alert {row['alert_id']}</a></p><p>{esc(line)}</p></li>")
        body.append("<ul class=\"tiles\">" + "".join(items) + "</ul>")
    else:
        body.append("<p>No open alerts.</p>")

    labels = conn.execute("SELECT * FROM labels ORDER BY state != 'extracted', label_id DESC").fetchall()
    body.append("<h2>Labels</h2>")
    if labels:
        rows = "".join(
            f"<tr><td><a href=\"/label/{row['label_id']}\">{esc(row['product_name'])}</a></td>"
            f"<td>{esc(row['epa_reg_no'] or '')}</td><td>{esc(row['product_type'])}</td><td>{tag(row['state'])}</td>"
            f"<td>{esc(row['source_file'])}</td></tr>" for row in labels)
        body.append("<div class=\"wrap\"><table><thead><tr><th>Product</th><th>EPA Reg. No.</th><th>Type</th>"
                    f"<th>State</th><th>File</th></tr></thead><tbody>{rows}</tbody></table></div>")
    else:
        body.append("<p>No labels yet. Drop label PDFs or photos in the inbox.</p>")

    body.append("<h2>Schedule</h2>")
    harvests = conn.execute("SELECT h.*, b.name, b.crop FROM harvests h JOIN blocks b USING (block_id) "
                            "ORDER BY planned_date, harvest_id").fetchall()
    entries = conn.execute("SELECT e.*, b.name FROM crew_entries e JOIN blocks b USING (block_id) "
                           "ORDER BY planned_at, entry_id").fetchall()
    rows = [f"<tr><td>{esc(r['planned_date'])}</td><td>Harvest {esc(r['harvest_id'])}</td><td>{esc(r['name'])}"
            f" ({esc(r['crop'])})</td><td>{esc(r['status'])}</td></tr>" for r in harvests]
    rows += [f"<tr><td>{esc(r['planned_at'].replace('T', ' '))}</td><td>{esc(r['crew'])}: {esc(r['task'] or '')}</td>"
             f"<td>{esc(r['name'])}</td><td>{esc(r['status'])}</td></tr>" for r in entries]
    body.append("<div class=\"wrap\"><table><thead><tr><th>When</th><th>What</th><th>Block</th><th>Status</th>"
                f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>" if rows else "<p>Nothing scheduled.</p>")

    body.append("<h2>Recent sprays</h2>")
    sprays = conn.execute("SELECT s.*, b.name FROM sprays s JOIN blocks b USING (block_id) "
                          "ORDER BY applied_at DESC LIMIT 30").fetchall()
    rows = "".join(
        f"<tr><td>{esc(r['applied_at'].replace('T', ' '))}</td><td>{esc(r['name'])}</td><td>{esc(r['product'])}</td>"
        f"<td>{esc(r['applicator'] or '')}</td><td><a href=\"/posting/{r['spray_id']}\">Posting</a></td></tr>"
        for r in sprays)
    body.append("<div class=\"wrap\"><table><thead><tr><th>Applied</th><th>Block</th><th>Product</th>"
                f"<th>Applicator</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>"
                if sprays else "<p>No sprays logged.</p>")
    return page("Today", "".join(body))


def binding_fact(conn: sqlite3.Connection, policy: dict, alert: sqlite3.Row, block: sqlite3.Row,
                 kind: str) -> sqlite3.Row | None:
    """The label fact the rule used: the crop's PHI, or the crop's REI before the general one."""
    aliases = {rules.crop_key(k, {}): rules.crop_key(v, {}) for k, v in policy.get("crop_aliases", {}).items()}
    wanted = rules.crop_key(block["crop"], aliases)
    facts = conn.execute("SELECT * FROM label_facts WHERE label_id = ? AND kind = ? ORDER BY hours DESC",
                         (alert["label_id"], kind)).fetchall()
    for fact in facts:
        if fact["crop"] != "*" and rules.crop_key(fact["crop"], aliases) == wanted:
            return fact
    if kind == "rei":
        for fact in facts:
            if fact["crop"] == "*":
                return fact
    return None


def render_alert(conn: sqlite3.Connection, config: Config, policy: dict, alert_id: int, query: dict) -> str | None:
    try:
        context = card.alert_context(conn, alert_id)
    except KeyError:
        return None
    alert, block, spray, label = context["alert"], context["block"], context["spray"], context["label"]
    try:
        line = unslack(card.alert_line(policy, context))
    except card.CardError as error:
        line = f"Alert {alert_id} ({error})"
    body = [f"<h1>Alert {alert_id}: {esc(alert['kind'].replace('_', ' '))} {tag(alert['state'])}</h1>",
            banner(query), f"<p><strong>{esc(line)}</strong></p>"]
    if alert["kind"] in ("harvest_conflict", "entry_conflict"):
        what = "Harvest" if alert["kind"] == "harvest_conflict" else f"Entry by {context['entry']['crew']}"
        rule = ("Pre-harvest interval: harvest date must be on or after the application date plus the PHI."
                if alert["reason"] == "phi" else
                "Restricted-entry interval: entry must be at or after the end of the application plus the REI"
                + (f" (a harvest starts at {policy['harvest_start_time']})." if alert["kind"] == "harvest_conflict"
                   else "."))
        body.append(
            "<h2>The rule, applied by code</h2><div class=\"wrap\"><table><tbody>"
            f"<tr><th scope=\"row\">Block</th><td>{esc(block['name'])} ({esc(block['crop'])})</td></tr>"
            f"<tr><th scope=\"row\">Spray</th><td>{esc(spray['product'])}, ended {esc(spray['applied_at'].replace('T', ' '))}"
            f"{', by ' + esc(spray['applicator']) if spray['applicator'] else ''} "
            f"(<a href=\"/posting/{spray['spray_id']}\">posting</a>)</td></tr>"
            f"<tr><th scope=\"row\">Interval</th><td>{esc(card.interval(alert['interval_hours'], alert['reason']))}"
            f" ({esc(alert['reason'].upper())})</td></tr>"
            f"<tr><th scope=\"row\">{esc(what)} scheduled</th><td>{esc(alert['scheduled'].replace('T', ' '))}</td></tr>"
            f"<tr><th scope=\"row\">Earliest legal</th><td><strong>{esc(alert['earliest'].replace('T', ' '))}</strong></td></tr>"
            f"</tbody></table></div><p class=\"muted\">{esc(rule)}</p>")
        fact = binding_fact(conn, policy, alert, block, alert["reason"])
        body.append(f"<h2>Proof from the label: <a href=\"/label/{label['label_id']}\">{esc(label['product_name'])}</a>"
                    "</h2>")
        body.append(fact_block(label, fact) if fact else "<p class=\"muted\">The fact isn't on file.</p>")
        if alert["state"] == "open":
            new = alert["earliest"].replace("T", " ")
            body.append("<h2>Decision</h2>" + form(
                config, "approve_alert", {"alert_id": alert_id}, approver_select(policy, "approver"),
                f"Approve the new date: {new}"))
        elif alert["decided_by"]:
            body.append(f"<p>{esc(alert['state'].capitalize())} by {esc(alert['decided_by'])} at "
                        f"{esc(alert['decided_at'])}.</p>")
    else:
        body.append(f"<p>Spray {spray['spray_id']}: {esc(spray['product'])} on {esc(block['name'])}, ended "
                    f"{esc(spray['applied_at'].replace('T', ' '))}.</p>")
        if label is not None:
            body.append(f"<p>Label: <a href=\"/label/{label['label_id']}\">{esc(label['product_name'])}</a> "
                        f"{tag(label['state'])}</p>")
        body.append("<p class=\"muted\">No interval is applied to this spray until it is fixed. Treat the block as "
                    "closed and don't harvest until the label is on file and confirmed.</p>")
    return page(f"Alert {alert_id}", "".join(body))


def render_label(conn: sqlite3.Connection, config: Config, policy: dict, label_id: int, query: dict) -> str | None:
    label = conn.execute("SELECT * FROM labels WHERE label_id = ?", (label_id,)).fetchone()
    if label is None:
        return None
    facts = conn.execute("SELECT * FROM label_facts WHERE label_id = ? ORDER BY kind DESC, crop, fact_id",
                         (label_id,)).fetchall()
    unverified = sum(1 for fact in facts if not fact["quote_verified"])
    body = [f"<h1>{esc(label['product_name'])} {tag(label['state'])}</h1>", banner(query),
            f"<p>EPA Reg. No. {esc(label['epa_reg_no'] or 'not read')} · {esc(label['product_type'])} · "
            f"read by {esc(label['model'])} from {esc(label['source_file'])} at {esc(label['extracted_at'])}</p>"]
    if not json.loads(label["pages_json"]):
        body.append(f"<p><a href=\"/label/{label_id}/source\">Open the photo</a></p>")
    if label["state"] == "extracted":
        checkbox = ""
        if unverified:
            checkbox = ("<p><input type=\"checkbox\" id=\"checked\" name=\"checked_myself\" value=\"1\">"
                        f"<label for=\"checked\">I checked the {unverified} unverified "
                        f"fact{'s' if unverified != 1 else ''} against the label myself</label></p>")
        body.append("<div class=\"card\"><p>The model read these facts. Code checked each quote against the label "
                    f"text: {len(facts) - unverified} verified, {unverified} unverified. No rule uses this label "
                    "until you confirm it.</p>"
                    + form(config, "confirm_label", {"label_id": label_id}, approver_select(policy, "approver-c")
                           + checkbox, "Confirm label")
                    + form(config, "reject_label", {"label_id": label_id}, approver_select(policy, "approver-r"),
                           "Reject label") + "</div>")
    elif label["decided_by"]:
        body.append(f"<p>{esc(label['state'].capitalize())} by {esc(label['decided_by'])} at "
                    f"{esc(label['decided_at'])}.</p>")
    body.append("<h2>Facts</h2>" + "".join(fact_block(label, fact) for fact in facts))
    return page(label["product_name"], "".join(body))


def render_spray_form(conn: sqlite3.Connection, config: Config, query: dict) -> str:
    blocks = conn.execute("SELECT * FROM blocks ORDER BY block_id").fetchall()
    if not blocks:
        return page("Log a spray", "<h1>Log a spray</h1><p>No blocks yet. Drop blocks.csv in the inbox.</p>")
    products = conn.execute("SELECT DISTINCT product_name FROM labels WHERE state = 'confirmed' "
                            "ORDER BY product_name").fetchall()
    options = "".join(f"<option value=\"{esc(b['block_id'])}\">{esc(b['name'])} ({esc(b['crop'])})</option>"
                      for b in blocks)
    names = "".join(f"<option value=\"{esc(p['product_name'])}\"></option>" for p in products)
    now = config.clock().strftime("%Y-%m-%dT%H:%M")
    inner = (f"<p><label for=\"block\">Block</label><select id=\"block\" name=\"block_id\" required>{options}</select></p>"
             f"<p><label for=\"product\">Product</label><input id=\"product\" name=\"product\" list=\"products\" "
             f"required maxlength=\"80\"><datalist id=\"products\">{names}</datalist></p>"
             "<p><label for=\"epa\">EPA Reg. No. (optional)</label><input id=\"epa\" name=\"epa_reg_no\" maxlength=\"20\"></p>"
             f"<p><label for=\"applied\">Application ended</label><input id=\"applied\" type=\"datetime-local\" "
             f"name=\"applied_at\" value=\"{esc(now)}\" required></p>"
             "<p><label for=\"applicator\">Applicator</label><input id=\"applicator\" name=\"applicator\" maxlength=\"80\"></p>")
    return page("Log a spray", "<h1>Log a spray</h1>" + banner(query)
                + "<p>The check runs as soon as the spray is saved: any harvest or crew entry it breaks is "
                  "alerted in Slack at once.</p>" + form(config, "log_spray", {}, inner, "Log spray"))


def render_posting(conn: sqlite3.Connection, policy: dict, spray_id: int, query: dict) -> str | None:
    if conn.execute("SELECT 1 FROM sprays WHERE spray_id = ?", (spray_id,)).fetchone() is None:
        return None
    try:
        sign = posting.build(conn, policy, spray_id)
    except posting.PostingError as error:
        return page("Posting", f"<h1>Posting for spray {spray_id}</h1>{banner(query)}"
                    f"<p class=\"banner banner-refused\">No posting yet: {esc(error)}.</p>")
    reg = f" (EPA Reg. No. {esc(sign.epa_reg_no)})" if sign.epa_reg_no else ""
    body = (f"<div class=\"noprint\"><h1>Do-not-enter posting: {esc(sign.block)}</h1>{banner(query)}"
            "<p class=\"muted\">Fixed wording, filled in by code from the spray log and the confirmed label. "
            "Check the label for whether a posted sign or an oral warning is required. "
            "<button onclick=\"window.print()\">Print</button></p></div>"
            f"<section class=\"sign\" lang=\"en\"><p class=\"head\">{'<br>'.join(map(esc, sign.headline_en))}</p>"
            f"<p>{esc(sign.body_en)}</p><p class=\"muted\">{esc(sign.product)}{reg}</p></section>"
            f"<section class=\"sign\" lang=\"es\"><p class=\"head\">{'<br>'.join(map(esc, sign.headline_es))}</p>"
            f"<p>{esc(sign.body_es)}</p><p class=\"muted\">{esc(sign.product)}{reg}</p></section>")
    return page(f"Posting {sign.block}", body)


# Actions -----------------------------------------------------------------------------------

def act(conn: sqlite3.Connection, config: Config, policy: dict, action: str, fields: dict) -> tuple[str, str]:
    """Run one action; returns (where to go, done message). Raises approval.Refused or store.RecordError."""
    today = config.clock().date()
    if action == "approve_alert":
        alert_id = int(fields.get("alert_id", "0"))
        queue_file = approval.approve_alert(conn, policy, alert_id, fields.get("approver", ""), today,
                                            config.queue_dir)
        return f"/alert/{alert_id}", f"Approved and queued as {queue_file.name}."
    if action == "confirm_label":
        label_id = int(fields.get("label_id", "0"))
        approval.confirm_label(conn, policy, label_id, fields.get("approver", ""),
                               fields.get("checked_myself") == "1")
        return f"/label/{label_id}", "Label confirmed. Its intervals now apply."
    if action == "reject_label":
        label_id = int(fields.get("label_id", "0"))
        approval.reject_label(conn, policy, label_id, fields.get("approver", ""))
        return f"/label/{label_id}", "Label rejected."
    if action == "log_spray":
        with conn:
            spray_id = store.add_spray(conn, fields.get("block_id"), fields.get("product"), fields.get("epa_reg_no"),
                                       fields.get("applied_at"), fields.get("applicator"), source="page",
                                       actor="page")
        if spray_id is None:
            raise store.RecordError("that spray is already logged")
        return f"/posting/{spray_id}", f"Spray {spray_id} logged and checked."
    raise KeyError(action)


class Handler(BaseHTTPRequestHandler):
    config: Config
    server_version = "SprayWatch"

    def log_message(self, format, *args):  # noqa: A002 - the base class's name
        sys.stderr.write(f"{db.now()} page: {format % args}\n")

    def send(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; script-src 'unsafe-inline'; "
                         "form-action 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ("127.0.0.1", "localhost")

    def do_GET(self):  # noqa: N802 - the base class's name
        if not self.host_ok():
            return self.send(HTTPStatus.FORBIDDEN, "Only the local browser may open this page.", "text/plain")
        url = urllib.parse.urlsplit(self.path)
        query = dict(urllib.parse.parse_qsl(url.query))
        parts = [part for part in url.path.split("/") if part]
        config = self.config
        policy = policy_loader.load(config.policy_path)
        conn = db.connect(config.db_path)
        try:
            body = None
            if not parts:
                body = render_index(conn, config, policy, query)
            elif parts == ["spray", "new"]:
                body = render_spray_form(conn, config, query)
            elif len(parts) == 2 and parts[1].isdigit():
                number = int(parts[1])
                if parts[0] == "alert":
                    body = render_alert(conn, config, policy, number, query)
                elif parts[0] == "label":
                    body = render_label(conn, config, policy, number, query)
                elif parts[0] == "posting":
                    body = render_posting(conn, policy, number, query)
            elif len(parts) == 3 and parts[0] == "label" and parts[1].isdigit() and parts[2] == "source":
                return self.send_photo(conn, int(parts[1]))
            if body is None:
                return self.send(HTTPStatus.NOT_FOUND, page("Not found", "<h1>Not found</h1>"))
            return self.send(HTTPStatus.OK, body)
        finally:
            conn.close()

    def send_photo(self, conn: sqlite3.Connection, label_id: int):
        from labels import extract

        row = conn.execute("SELECT source_file, source_sha256, pages_json FROM labels WHERE label_id = ?",
                           (label_id,)).fetchone()
        path = self.config.inbox_dir / row["source_file"] if row else None
        if (row is None or json.loads(row["pages_json"]) or not path.is_file()
                or path.suffix.lower() not in extract.IMAGE_SUFFIXES or extract.sha256(path) != row["source_sha256"]):
            return self.send(HTTPStatus.NOT_FOUND, page("Not found", "<h1>The photo isn't in the inbox</h1>"))
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", extract.IMAGE_SUFFIXES[path.suffix.lower()])
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802 - the base class's name
        if not self.host_ok():
            return self.send(HTTPStatus.FORBIDDEN, "Only the local browser may use this page.", "text/plain")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_FORM_BYTES:
            return self.send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Form too large.", "text/plain")
        fields = dict(urllib.parse.parse_qsl(self.rfile.read(length).decode("utf-8", "replace")))
        if not secrets.compare_digest(fields.get("token", ""), self.config.token):
            return self.send(HTTPStatus.FORBIDDEN, "Stale or missing form token: reload the page.", "text/plain")
        parts = [part for part in urllib.parse.urlsplit(self.path).path.split("/") if part]
        if len(parts) != 2 or parts[0] != "action":
            return self.send(HTTPStatus.NOT_FOUND, "No such action.", "text/plain")
        config = self.config
        policy = policy_loader.load(config.policy_path)
        conn = db.connect(config.db_path)
        back = self.headers.get("Referer", "/")
        back = urllib.parse.urlsplit(back).path or "/"
        try:
            try:
                where, done = act(conn, config, policy, parts[1], fields)
            except KeyError:
                return self.send(HTTPStatus.NOT_FOUND, "No such action.", "text/plain")
            except (approval.Refused, store.RecordError, ValueError) as error:
                return self.redirect(f"{back}?{urllib.parse.urlencode({'refused': str(error)})}")
            # Every decision changes what the rules see: check now, so Slack hears at once.
            report = check.run_pass(conn, policy, config.poster, config.base_url, config.clock())
            if report.raised:
                done += f" {len(report.raised)} new alert{'s' if len(report.raised) != 1 else ''} raised."
            return self.redirect(f"{where}?{urllib.parse.urlencode({'done': done})}")
        finally:
            conn.close()


def make_server(config: Config) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"config": config})
    return ThreadingHTTPServer((config.host, config.port), handler)


def main() -> int:
    config = Config.from_env()
    db.connect(config.db_path).close()
    server = make_server(config)
    print(f"page: http://127.0.0.1:{config.port}/ (database {config.db_path})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
