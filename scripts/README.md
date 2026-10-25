# scripts

| Script | What |
| --- | --- |
| `validate_repo.py` | `make check`: required files, contract terms, banned file types, Markdown links |
| `scan_secrets.py` | `make check` and pre-commit: credentials in tracked or staged files |
| `check_pr_issue.py` | CI: a pull request must name its issue |
| `install-hooks.sh` | Once per clone: pre-commit and pre-push hooks |
| `make_pdf.py` | A text file into a PDF with a real text layer, for the demo labels and tests |
| `read_label.py` | One label through the live model, showing what code verified; `--save-reply` for the fakes |
| `fetch_labels.sh` | The real labels in `demo/real-labels.tsv`, checked by SHA-256, into `state/labels/` |
| `demo.py` | The demo farm with today's dates; `--live` for the real model |
