# agent

SQLite, the rules, the inbox watcher, the check pass, the Slack cards, approval and the postings. Standard library only.

| File | What |
| --- | --- |
| `db.py` | The tables and the event log, as the contract's "SQLite tables" says |
| `rules.py` | The PHI and REI rules: pure functions, no SQLite, no clock |
| `store.py` | Every write of labels, blocks, sprays and the schedule; CSV imports; `load_state` for the rules |
| `watch.py` | The folder watcher: each inbox file once, by SHA-256, then a check pass |
| `check.py` | One pass: findings into alerts, then due cards and the morning digest. The recurring job |
| `card.py` | Cards from the policy's templates; refuses any field outside the contract |
| `slack.py` | Delivers a finished card: Slack, a print, or nothing until Slack is set |
| `approval.py` | Approve a new date (and queue it), confirm or reject a label; refusals are logged |
| `posting.py` | The do-not-enter posting, in English and Spanish, from fixed wording |
