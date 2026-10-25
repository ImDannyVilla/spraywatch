#!/usr/bin/env python3
"""Write a plain text file as a PDF with a real text layer. Standard library only.

    python3 scripts/make_pdf.py label.txt label.pdf

Pages split on form feeds (or every 60 lines). Helvetica, 9 pt, Latin-1. Used
for the demo labels and the tests, so `pdftotext` has a real PDF to read.
"""
from __future__ import annotations

import sys
from pathlib import Path

LINES_PER_PAGE = 60


def _escape(line: str) -> bytes:
    data = line.encode("latin-1", "replace")
    return data.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def pages_of(text: str) -> list[list[str]]:
    pages = []
    for chunk in text.split("\f"):
        lines = chunk.splitlines()
        for start in range(0, max(1, len(lines)), LINES_PER_PAGE):
            pages.append(lines[start:start + LINES_PER_PAGE])
    return [page for page in pages if page] or [[""]]


def pdf_bytes(text: str) -> bytes:
    pages = pages_of(text)
    objects: list[bytes] = []
    # 1 catalog, 2 pages, 3 font, then a page and its content stream for each page.
    kids = " ".join(f"{4 + 2 * index} 0 R" for index in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for index, lines in enumerate(pages):
        content = b"BT /F1 9 Tf 11 TL 40 760 Td\n" + b"".join(
            b"(" + _escape(line) + b") Tj T*\n" for line in lines) + b"ET"
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
                       f"/Contents {5 + 2 * index} 0 R >>".encode())
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    Path(argv[1]).write_bytes(pdf_bytes(Path(argv[0]).read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
