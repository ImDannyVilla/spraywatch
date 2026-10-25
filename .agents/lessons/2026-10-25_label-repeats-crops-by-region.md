---
date: 2026-10-25
issue:
area: other
severity: important
---

# A real label lists the same crop more than once, and the reader kept only the first

## What happened

The first live read of the real Captan 80 DF label (EPA Reg. No. 42750-231) verified 27 of 27 facts, but the label has sections such as "APPLES: (East of the Rockies)" and "APPLES: (West of the Rockies)", and "GRAPES: (U.S. except CA)" and "GRAPES: (California only)". Qwen merged them into one entry per crop, and `labels/reader.py` dropped any repeat of a crop it had already seen. Had the two regions differed, the less strict value could have been kept without anyone seeing it.

## Root cause

The `spraywatch.label/1` shape had no way to say which region or use a value was for, so the prompt asked for one entry per crop and the reader de-duplicated by crop name.

## Fix

- Each crop entry may carry a `condition` (the region, variety or use as printed). The prompt asks for one entry per condition.
- The reader keeps every (crop, condition) pair; `label_facts.condition` stores it, and the page shows it.
- `rules.intervals` already took the strictest of several facts for a crop; the contract now says so (rule 3).

After the fix, the same label read 41 of 41 facts verified, with every regional variant kept, in 44 s.

## Prevention

`tests/test_reader.py::ParseTest::test_a_crop_given_twice_keeps_both_and_the_rules_take_the_stricter`, and `test_the_real_captan_label` once the label is fetched. Read one real label live after any prompt change (AGENTS.md, Definition of done).
