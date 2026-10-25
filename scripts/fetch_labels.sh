#!/bin/sh
# Download the real labels in demo/real-labels.tsv into a folder (default state/labels) and check each SHA-256.
# Labels are public PDFs from EPA's PPLS, but they stay out of git. Needs curl and sha256sum.
# A label whose checksum doesn't match is deleted: EPA may have replaced the file, so update the line by hand.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/state/labels}"
mkdir -p "$OUT"

grep -v '^#' "$ROOT/demo/real-labels.tsv" | while IFS="$(printf '\t')" read -r name sha url; do
    [ -n "$name" ] || continue
    if [ -f "$OUT/$name" ] && [ "$(sha256sum "$OUT/$name" | cut -d' ' -f1)" = "$sha" ]; then
        echo "fetch_labels: $name already here"
        continue
    fi
    curl -fsSL --max-time 120 -A "SprayWatch label fetch" -o "$OUT/$name.part" "$url"
    if [ "$(sha256sum "$OUT/$name.part" | cut -d' ' -f1)" != "$sha" ]; then
        rm -f "$OUT/$name.part"
        echo "fetch_labels: $name changed upstream; check it and update demo/real-labels.tsv" >&2
        exit 1
    fi
    mv "$OUT/$name.part" "$OUT/$name"
    echo "fetch_labels: $name from $url"
done
