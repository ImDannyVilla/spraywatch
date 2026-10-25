# Agent and contributor instructions

## Project

SprayWatch is a local agent that keeps a farm's harvests and crew entries inside every pesticide label's pre-harvest interval (PHI) and restricted-entry interval (REI). It reads the labels with a local model, keeps the spray log and the schedule in SQLite, applies the rules in code, alerts in Slack, and lets the manager approve the corrected date on a local page. It is the backup project for ClearFrame, built from the same pieces on one Dell Pro Max GB10. [`contracts/README.md`](contracts/README.md) is the source of truth for names, file shapes and rules; running it on the GB10 is in [`docs/gb10.md`](docs/gb10.md).

## Before you change anything

1. Read `contracts/README.md` and the `README.md` of every folder you will edit.
2. Work from your GitHub issue and stay inside its folder:

   | Folder | What | Proposed owner |
   | --- | --- | --- |
   | `labels/` | Label files to text, the model client, the reader and the quote check | Danny |
   | `agent/` | SQLite, the rules, the inbox watcher, the check pass, cards, approval, postings | Gael |
   | `evidence/` | The local page | Jason |
   | `policy/` | Approvers, times, crop aliases, card templates | Danny |
   | `scripts/` | The gate, the demo, label tools | Danny |
   | `contracts/` | Everyone, by pull request only | Everyone |

3. Search `.agents/lessons/` for pitfalls in the area you are touching.

## Hard rules

The gates enforce what they can; the rest is on you.

- **The model only reads labels.** It proposes facts with a page, line and quote. Code checks every quote, a person confirms the label, and only code decides whether a harvest or entry is legal. Never let a model answer decide a rule.
- **Never treat an unknown as safe.** A product with no confirmed label, or a crop the label doesn't list, raises an alert. A crop listed more than once keeps the strictest value.
- **No model text reaches Slack or a posting.** Cards and postings come from the fixed templates in `policy/policy.json` and `agent/posting.py`. The confirmed product name and type are the only label-derived words they carry.
- **Nothing leaves the box** but the Slack card. No code calls a cloud model or a cloud API.
- **No label files, database, `.env`, tokens or keys in git.** Real labels are public, but `scripts/fetch_labels.sh` downloads them instead. `make check` scans for credentials and banned file types.
- **Standard library only** in `agent/`, `labels/`, `evidence/` and `policy/`. PDFs are read with poppler's `pdftotext`.
- **The contract changes only by pull request**, in the same pull request as its samples and tests, with a teammate's look before it merges.
- **Never weaken or skip a gate to make your change pass.** If a gate is wrong, fix it in its own commit and say why.
- **Demo labels are fictional** (`DEMO LABEL - NOT A REAL PRODUCT`). Never present them as real products, and never present SprayWatch's output as legal advice: the label is the law.

## Definition of done

- `make verify` passes. CI runs it on every push and pull request.
- A behavior change comes with a test in `tests/`. Tests need no model, no Slack and no network: they use the demo labels and the model's saved replies in `demo/replies/`.
- A prompt change is checked live on one real label with `scripts/read_label.py` before it merges, and the saved replies are refreshed.
- The diff touches only your folder, unless your issue says otherwise.

## Workflow

- Run `scripts/install-hooks.sh` once per clone, on laptops and on the GB10. Pre-commit runs the staged secret scan and `make check`; pre-push runs `make verify`.
- One branch per issue (`<name>/<issue>-<slug>`), small pull requests, and a normal merge, not squash. You may merge your own pull request once `make verify` passes, except contract changes.
- Every pull request names its issue in its description: `Closes #N` when it finishes the issue, or `Part of #N` when work remains. CI fails a pull request without one (`scripts/check_pr_issue.py`). If work is left when an issue's pull request merges, move it to a new issue first.
- When you or an agent get something wrong in a way that wasn't obvious, write a lesson in `.agents/lessons/`. If it can be checked, add the check to `scripts/validate_repo.py` or a test, and note that in the lesson.

## Git

- Do not add co-author lines (such as `Co-Authored-By`) to commit messages or pull request bodies.
