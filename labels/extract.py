"""A label file into what the model reads: pages of text, or a photo. Standard library only.

PDFs go through poppler's `pdftotext -layout` (on the GB10 and in CI), one page
per form feed. Photos are sent to the model as an image; there is no text to
check quotes against, so their facts are always unverified.
"""
from __future__ import annotations

import base64
import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

PDF_SUFFIXES = (".pdf",)
IMAGE_SUFFIXES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
# Text labels are for tests and demos that have no PDF tools.
TEXT_SUFFIXES = (".txt",)
LABEL_SUFFIXES = PDF_SUFFIXES + tuple(IMAGE_SUFFIXES) + TEXT_SUFFIXES
MAX_IMAGE_BYTES = 12 * 1024 * 1024


class ExtractError(RuntimeError):
    pass


@dataclass(frozen=True)
class LabelSource:
    path: Path
    sha256: str
    pages: tuple[tuple[str, ...], ...]  # pages of lines; empty for a photo
    image: tuple[str, str] | None = None  # (media type, base64) for a photo

    @property
    def is_photo(self) -> bool:
        return self.image is not None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_pages(text: str) -> tuple[tuple[str, ...], ...]:
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return tuple(tuple(line.rstrip() for line in page.splitlines()) for page in pages)


def pdf_text(path: Path) -> str:
    if shutil.which("pdftotext") is None:
        raise ExtractError("pdftotext is not installed (apt install poppler-utils)")
    done = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
                          capture_output=True, timeout=120)
    if done.returncode != 0:
        raise ExtractError(f"pdftotext failed on {path.name}: {done.stderr.decode('utf-8', 'replace')[:200]}")
    return done.stdout.decode("utf-8", "replace")


def load(path: Path) -> LabelSource:
    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        pages = split_pages(pdf_text(path))
        if not any(line.strip() for page in pages for line in page):
            raise ExtractError(f"{path.name} has no text layer; photograph the label or OCR it first")
        return LabelSource(path, sha256(path), pages)
    if suffix in TEXT_SUFFIXES:
        return LabelSource(path, sha256(path), split_pages(path.read_text(encoding="utf-8")))
    if suffix in IMAGE_SUFFIXES:
        data = path.read_bytes()
        if len(data) > MAX_IMAGE_BYTES:
            raise ExtractError(f"{path.name} is over {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
        return LabelSource(path, sha256(path), (), (IMAGE_SUFFIXES[suffix], base64.b64encode(data).decode("ascii")))
    raise ExtractError(f"not a label file: {path.name}")


def numbered_text(pages: tuple[tuple[str, ...], ...]) -> str:
    """The label as the model sees it: every line prefixed with its page and line number."""
    out = []
    for page_number, lines in enumerate(pages, start=1):
        out.append(f"=== page {page_number} ===")
        for line_number, line in enumerate(lines, start=1):
            if line.strip():
                out.append(f"p{page_number} L{line_number}: {line.strip()}")
    return "\n".join(out)
