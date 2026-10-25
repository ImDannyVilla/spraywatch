# tests

`make test`. No model, no Slack, no network: the tests read the demo labels in `demo/labels/` and Qwen's saved replies in `demo/replies/`. The PDF tests need `pdftotext`; the real-label test runs only after `scripts/fetch_labels.sh`.

| File | What |
| --- | --- |
| `test_rules.py` | The PHI and REI rules, label matching, alert keys |
| `test_reader.py` | The reply shape, the quote check, PDFs, the real Captan label |
| `test_flow.py` | Inbox, confirm, check, cards, digest, approve, queue, postings |
| `test_server.py` | The local page over HTTP: pages, token, Host check, escaping |
| `test_contract_samples.py` | The samples and the code match the contract |
| `test_check_pr_issue.py` | The pull-request issue check |
