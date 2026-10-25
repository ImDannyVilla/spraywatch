#!/usr/bin/env python3
"""Read one label with the model and show what code verified. Writes nothing to SQLite.

    python3 scripts/read_label.py label.pdf                       # the model from MODEL_* or --env
    python3 scripts/read_label.py label.pdf --env ~/spraywatch-input/model.env
    python3 scripts/read_label.py label.pdf --save-reply demo/replies/label.json

Use it after any prompt change, on one real label, before trusting a full run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from labels import extract, model as model_module, reader  # noqa: E402


class Recording:
    """Wraps the model to keep its raw reply."""

    def __init__(self, inner):
        self.inner = inner
        self.name = inner.name
        self.reply = None

    def ask(self, content):
        self.reply = self.inner.ask(content)
        return self.reply


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("label", type=Path)
    parser.add_argument("--env", type=Path, help="env file with MODEL_URL, MODEL_NAME, MODEL_API_KEY")
    parser.add_argument("--save-reply", type=Path, help="save the model's raw reply, for a fake in tests")
    args = parser.parse_args(argv)
    source = extract.load(args.label)
    model = Recording(model_module.ChatClient.from_env(args.env))
    try:
        label = reader.read(source, model)
    except (reader.ReplyError, model_module.ModelError) as error:
        print(f"read_label: {error}", file=sys.stderr)
        if model.reply is not None:
            print(model.reply.text, file=sys.stderr)
        return 1
    finally:
        if args.save_reply and model.reply is not None:
            args.save_reply.write_text(model.reply.text.strip() + "\n", encoding="utf-8")
    print(f"{label.product_name} ({label.product_type}), EPA Reg. No. {label.epa_reg_no}, "
          f"read in {label.reply_seconds:.1f} s by {model.name}")
    for fact in label.facts:
        mark = "verified  " if fact.quote_verified else "UNVERIFIED"
        crop = fact.crop + (f" ({fact.condition})" if fact.condition else "")
        print(f"  {mark} {fact.kind} {crop:<28} {fact.value:g} {fact.unit:<5} p{fact.page} L{fact.line}: "
              f"{json.dumps(fact.quote)}")
    verified = sum(fact.quote_verified for fact in label.facts)
    print(f"{verified} of {len(label.facts)} facts verified against the label text")
    return 0


if __name__ == "__main__":
    sys.exit(main())
