# The SprayWatch contract

This file is the source of truth for names, file shapes and rules. Code, tests and samples follow it. It changes only by pull request, in the same pull request as its samples and tests.

## What SprayWatch does

Every pesticide label sets a **pre-harvest interval** (PHI: the minimum days between an application and harvest) and a **restricted-entry interval** (REI: how long workers must stay out of a treated block). SprayWatch reads the labels, keeps the spray log and the harvest and crew schedule in SQLite, applies both intervals in code, and alerts in Slack when the schedule breaks one. The manager approves the corrected date on the local page.

- **The model only reads labels.** Qwen proposes the product, both intervals and the per-crop limits, each with the page, line and words it read them from. Code checks every quote against the label text. A person confirms the label before any rule uses it.
- **Code applies every rule.** No model output decides whether a harvest or an entry is legal.
- **No model text reaches Slack or the posting.** Cards and do-not-enter postings come from fixed templates in `policy/policy.json`. The only label-derived words they carry are the confirmed product name and product type.
- **Nothing leaves the box** except the Slack card.

## Time

All times are farm-local, without an offset: dates as `YYYY-MM-DD`, times as `YYYY-MM-DDTHH:MM`. A spray's `applied_at` is when the application **ended**.

## The rules

These are applied by `agent/rules.py`, exactly as written here.

1. **PHI.** A block may be harvested on date `H` after a spray applied on date `A` only if `H >= A + phi_days`. A 7-day PHI on a Monday spray means harvest no earlier than the next Monday. A PHI of 0 means the same day, subject to the REI.
2. **REI.** A person may enter a block at time `T` after a spray that ended at `applied_at` only if `T >= applied_at + rei_hours`. A harvest is an entry at the policy's `harvest_start_time` on its date.
3. **Which interval.** The label's per-crop value wins over its general value. When the label gives a crop more than once, the strictest value wins. The crop is the block's crop, matched to the label's crops after lower-casing, trimming and the policy's `crop_aliases`.
4. **Which sprays.** Every spray on the block applied before the harvest or entry. The binding spray is the one that gives the latest earliest-legal time.
5. **Which schedule.** Harvests with status `planned` and crew entries with status `planned`, from today on.
6. **Which labels.** Only labels in state `confirmed`, matched by EPA registration number, then by product name. A spray whose product matches no label, or only an unconfirmed one, or a label without the block's crop, raises an alert instead of being treated as safe, if it was applied in the last 30 days or a planned harvest or entry on its block comes after it.
7. **The fix.** The proposed harvest date is the earliest date that satisfies rules 1 and 2 for every spray. The proposed entry time is the earliest time that satisfies rule 2.

SprayWatch doesn't decide whether a label or the Worker Protection Standard requires a posted sign or an oral warning. It drafts the posting; the manager decides where it goes up.

## Alert kinds

| Kind | Raised when | Approve does |
| --- | --- | --- |
| `harvest_conflict` | A planned harvest breaks rule 1 or 2 | Moves the harvest to the proposed date and queues the change |
| `entry_conflict` | A planned crew entry breaks rule 2 | Moves the entry to the proposed time and queues the change |
| `unknown_product` | A spray's product matches no label | Nothing: add the label to the inbox |
| `label_unconfirmed` | A spray's product matches only an unconfirmed label | Nothing: confirm the label on its page |
| `crop_not_on_label` | The block's crop isn't on the product's label | Nothing: check the label and the spray |

Alert states: `open`, `approved`, `resolved` (the conflict is gone because the schedule or a label changed). An alert's `alert_key` names the conflict exactly, so the same conflict is never raised or posted twice, and a changed conflict is a new alert.

## Label states

`extracted` (read by the model, waiting for a person), `confirmed`, `rejected`. Every label fact carries `quote_verified`: 1 when code found the quote on the cited page within two lines of the cited line and the number in it matches the value, else 0. Confirming a label with an unverified fact needs the approver to tick that they checked the label themselves.

## The label reply: `spraywatch.label/1`

What the model must return, and what `labels/reader.py` validates. A sample is in [`samples/label-reply.json`](samples/label-reply.json).

| Field | Type | Rule |
| --- | --- | --- |
| `schema` | string | `spraywatch.label/1` |
| `product_name` | string | 1 to 60 characters: letters, digits, spaces and `-.,%/()®™&+'` |
| `epa_reg_no` | string or null | Digits and hyphens, like `100-1234` or `66330-48-264` |
| `product_type` | string | `fungicide`, `insecticide`, `herbicide`, `miticide`, `other` |
| `rei` | interval | The general REI |
| `crops` | list | Each `{crop, condition, phi, rei}`; `rei` may be null to use the general one; `condition` is optional |

A crop the label gives more than once (by region, variety or use) is listed once per `condition`, and the rules keep the strictest value across them: SprayWatch doesn't know which region or use applies.

An **interval** is `{value, unit, page, line, quote}`: `value` a number of 0 or more, `unit` `hours` or `days`, `page` and `line` the 1-based numbers shown to the model, `quote` the label's words.

## SQLite tables

One file, `state/spraywatch.db` by default. Rows are never deleted, and `events` is append-only.

| Table | Columns |
| --- | --- |
| `blocks` | `block_id`, `name`, `crop`, `acres` |
| `labels` | `label_id`, `product_name`, `epa_reg_no`, `product_type`, `state`, `source_file`, `source_sha256`, `pages_json`, `model`, `extracted_at`, `decided_by`, `decided_at` |
| `label_facts` | `fact_id`, `label_id`, `crop` (`*` for the general REI), `kind` (`phi` or `rei`), `condition`, `value`, `unit`, `hours` (the value in hours), `page`, `line`, `quote`, `quote_verified` |
| `sprays` | `spray_id`, `block_id`, `product`, `epa_reg_no`, `applied_at`, `applicator`, `source`, `logged_at` |
| `harvests` | `harvest_id`, `block_id`, `planned_date`, `status`, `updated_at` |
| `crew_entries` | `entry_id`, `block_id`, `crew`, `task`, `planned_at`, `status`, `updated_at` |
| `alerts` | `alert_id`, `alert_key`, `kind`, `state`, `block_id`, `spray_id`, `label_id`, `harvest_id`, `entry_id`, `scheduled`, `earliest`, `reason`, `interval_hours`, `created_at`, `decided_by`, `decided_at` |
| `events` | `event_id`, `at`, `actor`, `kind`, `detail` |

Event kinds: `label_extracted`, `label_failed`, `label_confirmed`, `label_rejected`, `spray_logged`, `schedule_imported`, `alert_raised`, `alert_resolved`, `alert_approved`, `approval_refused`, `card_posted`, `digest_posted`, `queued`.

## The inbox

`agent/watch.py` watches one folder. Each file is handled once, by its SHA-256:

| File | What happens |
| --- | --- |
| `*.pdf` | Text by `pdftotext -layout`, one page per form feed, read by the model as text |
| `*.png`, `*.jpg`, `*.jpeg` | A photo of a label, read by the model as an image. Quotes can't be checked against text, so every fact is unverified |
| `blocks.csv` | `block_id,name,crop,acres`; upserts |
| `sprays*.csv` | `block_id,product,epa_reg_no,applied_at,applicator`; appends |
| `harvests*.csv` | `harvest_id,block_id,planned_date`; upserts while the harvest is `planned` |
| `crew*.csv` | `entry_id,block_id,crew,task,planned_at`; upserts while the entry is `planned` |

After every file, the check runs: rules, alerts, cards.

## Slack cards

Built by `agent/card.py` from the templates in `policy/policy.json`. A card carries only these fields: block name, crop, product name and type from a confirmed label, the spray's applied date, the interval in days or hours, the scheduled and earliest-legal dates or times, the crew name, the alert kind, and the link to the local page. The link is always `http://127.0.0.1:<port>/...`.

- **Alert card**: once per alert, when it's raised.
- **Spray card**: once per logged spray, with the REI end and the posting link.
- **Morning digest**: once per day, after `morning_time`, listing every open alert, or saying there are none.

## The approval queue: `spraywatch.queue/1`

An approved schedule change is written to `queue/schedule-change-<alert_id>.json`, for the farm's scheduling tool or crew lead. Written once; never overwritten. A sample is in [`samples/queue-change.json`](samples/queue-change.json).

| Field | What |
| --- | --- |
| `schema` | `spraywatch.queue/1` |
| `alert_id`, `kind` | The alert approved |
| `block_id`, `harvest_id` or `entry_id` | What moves |
| `from`, `to` | The old and new date or time |
| `reason` | `phi` or `rei` |
| `spray_id`, `label_id` | The binding spray and its label |
| `approver`, `approved_at` | Who and when |

## The local page

`evidence/server.py`, on `127.0.0.1:8091` only. Every write is a POST with the page's form token and a loopback `Host` header.

| Path | What |
| --- | --- |
| `/` | Open alerts, labels waiting, blocks and the schedule |
| `/alert/<id>` | The conflict, the binding spray, the label line as proof, Approve |
| `/label/<id>` | Every fact with its quote and the label page around it, Confirm and Reject |
| `/spray/new` | Log a spray; the check runs at once |
| `/inbox/new` | Add label PDFs or photos and the CSV files to the inbox, for the watcher. Takes only `.pdf`, `.png`, `.jpg` and the CSV names in "The inbox"; never overwrites a different file; refused when the inbox is read-only |
| `/posting/<spray_id>` | The do-not-enter posting, in English and Spanish, ready to print |
