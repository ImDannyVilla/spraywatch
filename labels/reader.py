"""Reading a label with the model, and checking what it says. Standard library only.

The model proposes the product, both intervals and the per-crop limits, each
with the page, line and words it read them from (`spraywatch.label/1`). This
module refuses any reply outside that shape, then checks every quote against
the label text: the quote must be on the cited page within two lines of the
cited line, and the number in it must be the value. Facts that pass are
`quote_verified`. Nothing here decides whether a harvest is legal.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from labels import extract
from labels.model import Model, ModelError

SCHEMA = "spraywatch.label/1"
PRODUCT_TYPES = ("fungicide", "insecticide", "herbicide", "miticide", "other")
UNITS = ("hours", "days")
PRODUCT_NAME = re.compile(r"[A-Za-z0-9 \-.,%/()®™&+']{1,60}")
EPA_REG_NO = re.compile(r"[0-9]{1,7}(?:-[0-9]{1,7}){1,3}")
MAX_CROPS = 80
MAX_QUOTE = 400
# Within this many lines of the cited line, a quote counts as found where cited.
LINE_SLACK = 2

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fourteen": 14, "fifteen": 15, "twenty": 20,
    "twenty-one": 21, "thirty": 30, "forty-eight": 48, "seventy-two": 72,
}
SAME_DAY = re.compile(r"day of harvest|up to (?:and including )?harvest|until harvest", re.IGNORECASE)

PROMPT = """You are reading a pesticide label for a farm's spray log. Find:

1. The product name, as printed, and the EPA registration number ("EPA Reg. No.").
2. The product type: fungicide, insecticide, herbicide, miticide or other.
3. The general restricted-entry interval (REI): how long workers must stay out after application.
4. For every crop the label allows, the pre-harvest interval (PHI): the minimum days from application to harvest. If a crop has its own REI, give it too; otherwise give null.

Every interval must cite where you read it: the page number and line number shown at the start of the line (`p3 L42:` is page 3, line 42), and the exact words from that line, copied character for character. Copy only words that are on the label. If the label says "day of harvest", the PHI is 0 days.

Reply with only one JSON object, no other text, in this shape:

{"schema": "spraywatch.label/1",
 "product_name": "Example 50 WP",
 "epa_reg_no": "1234-56",
 "product_type": "fungicide",
 "rei": {"value": 24, "unit": "hours", "page": 1, "line": 12, "quote": "Do not enter or allow worker entry into treated areas during the restricted entry interval (REI) of 24 hours"},
 "crops": [
  {"crop": "strawberry", "phi": {"value": 0, "unit": "days", "page": 3, "line": 40, "quote": "May be applied up to the day of harvest"}, "rei": null},
  {"crop": "grape", "phi": {"value": 7, "unit": "days", "page": 4, "line": 8, "quote": "Do not apply within 7 days of harvest"}, "rei": {"value": 3, "unit": "days", "page": 4, "line": 9, "quote": "REI is 3 days for girdling and cane turning"}}
 ]}

Use the crop name as the label prints it, singular, without the region. If the label gives a crop more than once (by region, variety or use), list each one separately with the same crop name and put the region or condition, as printed, in "condition", for example {"crop": "cherry", "condition": "West of the Rockies", "phi": ..., "rei": ...}. Otherwise leave "condition" out. Units are "hours" or "days"."""

PHOTO_NOTE = ("\n\nThis label is a photo, with no page or line numbers. Use page 1 and line 0, and copy the "
              "exact words you read.")


class ReplyError(ValueError):
    """The model's reply isn't a `spraywatch.label/1` object."""


@dataclass(frozen=True)
class ReadFact:
    crop: str  # "*" for the general REI
    kind: str  # "phi" or "rei"
    condition: str | None  # a region, variety or use the label names; the rules keep the strictest
    value: float
    unit: str
    hours: float
    page: int
    line: int
    quote: str
    quote_verified: bool


@dataclass(frozen=True)
class ReadLabel:
    product_name: str
    epa_reg_no: str | None
    product_type: str
    facts: tuple[ReadFact, ...]
    reply_seconds: float


# Asking -------------------------------------------------------------------------------------

def content_for(source: extract.LabelSource) -> list[dict]:
    if source.is_photo:
        media, data = source.image
        return [{"type": "text", "text": PROMPT + PHOTO_NOTE},
                {"type": "image_url", "image_url": {"url": f"data:{media};base64,{data}"}}]
    return [{"type": "text", "text": PROMPT + "\n\nThe label:\n\n" + extract.numbered_text(source.pages)}]


def read(source: extract.LabelSource, model: Model) -> ReadLabel:
    reply = model.ask(content_for(source))
    if reply.finish_reason == "length":
        raise ModelError("the reply was cut off at max_tokens")
    data = parse_reply(reply.text)
    return validate(data, source, reply.seconds)


# Parsing ------------------------------------------------------------------------------------

def parse_reply(text: str) -> dict:
    """The one JSON object in the reply. Code fences and text around it are tolerated, nothing else."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ReplyError("no JSON object in the reply")
    try:
        data = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as error:
        raise ReplyError(f"the reply isn't valid JSON: {error.msg}") from None
    if not isinstance(data, dict):
        raise ReplyError("the reply isn't a JSON object")
    return data


def _interval(raw, where: str) -> dict:
    if not isinstance(raw, dict):
        raise ReplyError(f"{where} must be an interval object")
    value, unit = raw.get("value"), raw.get("unit")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 10000:
        raise ReplyError(f"{where}.value must be a number from 0")
    if unit not in UNITS:
        raise ReplyError(f"{where}.unit must be hours or days")
    page, line = raw.get("page"), raw.get("line")
    for name, number in (("page", page), ("line", line)):
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise ReplyError(f"{where}.{name} must be a whole number")
    quote = raw.get("quote")
    if not isinstance(quote, str) or not quote.strip() or len(quote) > MAX_QUOTE:
        raise ReplyError(f"{where}.quote must be the label's words, up to {MAX_QUOTE} characters")
    return {"value": float(value), "unit": unit, "page": page, "line": line, "quote": " ".join(quote.split())}


def validate(data: dict, source: extract.LabelSource, seconds: float = 0.0) -> ReadLabel:
    if data.get("schema") != SCHEMA:
        raise ReplyError(f"schema must be {SCHEMA}")
    name = data.get("product_name")
    if not isinstance(name, str) or not PRODUCT_NAME.fullmatch(name.strip()):
        raise ReplyError("product_name must be 1 to 60 plain characters")
    reg = data.get("epa_reg_no")
    if reg is not None:
        if not isinstance(reg, str):
            raise ReplyError("epa_reg_no must be a string or null")
        reg = reg.strip().replace(" ", "")
        if not EPA_REG_NO.fullmatch(reg):
            reg = None  # an unreadable number isn't used for matching; the name still is
    product_type = data.get("product_type")
    if product_type not in PRODUCT_TYPES:
        raise ReplyError(f"product_type must be one of {', '.join(PRODUCT_TYPES)}")
    crops = data.get("crops")
    if not isinstance(crops, list) or not crops or len(crops) > MAX_CROPS:
        raise ReplyError(f"crops must list 1 to {MAX_CROPS} crops")
    facts = [_fact("*", "rei", None, _interval(data.get("rei"), "rei"), source)]
    seen = set()
    for index, crop in enumerate(crops):
        if not isinstance(crop, dict):
            raise ReplyError(f"crops[{index}] must be an object")
        crop_name = crop.get("crop")
        if not isinstance(crop_name, str) or not crop_name.strip() or len(crop_name) > 60 or crop_name.strip() == "*":
            raise ReplyError(f"crops[{index}].crop must be a crop name")
        crop_name = " ".join(crop_name.lower().split())
        condition = crop.get("condition")
        if condition is not None and (not isinstance(condition, str) or len(condition) > 80):
            raise ReplyError(f"crops[{index}].condition must be the label's words, up to 80 characters")
        condition = (" ".join(condition.split()) or None) if condition else None
        if (crop_name, condition) in seen:
            continue
        seen.add((crop_name, condition))
        facts.append(_fact(crop_name, "phi", condition, _interval(crop.get("phi"), f"crops[{index}].phi"), source))
        if crop.get("rei") is not None:
            facts.append(_fact(crop_name, "rei", condition, _interval(crop["rei"], f"crops[{index}].rei"), source))
    return ReadLabel(name.strip(), reg, product_type, tuple(facts), seconds)


def _fact(crop: str, kind: str, condition: str | None, interval: dict, source: extract.LabelSource) -> ReadFact:
    hours = interval["value"] * (24 if interval["unit"] == "days" else 1)
    page, line, verified = verify_quote(source, interval)
    return ReadFact(crop, kind, condition, interval["value"], interval["unit"], hours, page, line, interval["quote"], verified)


# Checking the quote -------------------------------------------------------------------------

def normalize(text: str) -> str:
    text = text.replace("’", "'").replace("–", "-").replace("—", "-").replace("­", "")
    return " ".join(text.lower().split())


def quote_has_value(quote: str, value: float, unit: str) -> bool:
    """The number in the quote is the value: digits, a number word, or "day of harvest" for 0."""
    if value == 0 and SAME_DAY.search(quote):
        return True
    numbers = {float(n) for n in re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])", quote)}
    lowered = normalize(quote)
    numbers |= {float(n) for word, n in NUMBER_WORDS.items() if re.search(rf"\b{word}\b", lowered)}
    if value in numbers:
        return True
    # "12 hours" read as 0.5 days, or "2 days" read as 48 hours.
    if unit == "days" and value * 24 in numbers and re.search(r"\bhours?\b|\bhrs?\b", lowered):
        return True
    if unit == "hours" and value % 24 == 0 and value / 24 in numbers and re.search(r"\bdays?\b", lowered):
        return True
    return False


def verify_quote(source: extract.LabelSource, interval: dict) -> tuple[int, int, bool]:
    """(page, line, verified): the quote found on its page near its line, with the right number.

    A quote found elsewhere on the page is reported where it really is, unverified,
    so a person looks. A photo has no text, so nothing is verified.
    """
    page, line = interval["page"], interval["line"]
    if source.is_photo or not quote_has_value(interval["quote"], interval["value"], interval["unit"]):
        return page, line, False
    if not 1 <= page <= len(source.pages):
        return page, line, False
    wanted = normalize(interval["quote"])
    lines = source.pages[page - 1]

    def found_at(first: int) -> bool:
        # The quote may wrap: join this line and the next three.
        window = normalize(" ".join(lines[first:first + 4]))
        return wanted in window or wanted in window.replace("- ", "")

    def start_of(index: int) -> int:
        # Every window up to the quote's first line contains it; the last such window starts on it.
        while index + 1 < len(lines) and found_at(index + 1):
            index += 1
        return index + 1

    near = [index for index in range(max(0, line - 1 - LINE_SLACK - 3), min(len(lines), line + LINE_SLACK))
            if found_at(index)]
    if near:
        start = start_of(near[0])
        return page, start, abs(start - line) <= LINE_SLACK
    for index in range(len(lines)):
        if found_at(index):
            return page, start_of(index), False
    return page, line, False
