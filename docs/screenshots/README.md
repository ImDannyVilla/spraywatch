# Screenshots

The local page on the demo farm, shown in the [README](../../README.md#screenshots). Retake them when the page changes:

1. Build the farm without the Captan label, so it arrives through the page: if `scripts/fetch_labels.sh` has fetched it, move `state/labels/captan-80-df.pdf` out of `state/labels/` first. Run `python3 scripts/demo.py`, and start the page with the command it prints.
2. On **Add files**, add `captan-80-df.pdf`. Then run one watcher pass with the saved replies, with the same `SPRAYWATCH_DB`, `SPRAYWATCH_INBOX` and `SPRAYWATCH_QUEUE` as the page: `SPRAYWATCH_FAKE_REPLIES=demo/replies python3 agent/watch.py --once`.
3. Take `03-label.png` before you confirm the label. Then confirm it, and log a Captan 80 DF spray (42750-231) on Block 1 ending at 16:00 today.
4. Shoot 1280 px wide at 2x, the whole page; cut the label page after its second fact.

Only PNG files directly in this folder may be committed (`scripts/validate_repo.py`): label photos stay out of git.
