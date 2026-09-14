# Complete intake and resumable review

Use the installed plugin's `scripts/review_discovery_queue.py`. Set `State/config.json` `require_review_queue` to `true` for new and repaired discovery workspaces. A queue file also enables enforcement automatically. Keep the queue, full public source snapshots, and review evidence inside the private workspace.

At the start of every run:

```sh
python3 scripts/review_discovery_queue.py --workspace "$WORKSPACE" --occurred-at "$NOW" --output "$RUN/pending.json" next
```

Review all returned queue items before expanding discovery. A `--limit` only limits the displayed work batch; it never marks the remaining queue complete. Deliver reviewed qualifying items, then check `status` again. If `can_expand_search` is false, continue existing work. Preserve unfinished work across context or time limits and report the run as partial.

Before selecting candidates from a new query, ingest **every returned listing**, including likely repeats and nonmatches. Input is an array of objects containing `source`, `source_record_id`, `employer`, `title`, `location`, `posting_url`, optional `requisition_id`, optional `raw_field_hash`, and `raw` with the full source `description` and available terms. Preserve the same raw hash and source ID used by delivery. Distinct known requisitions remain distinct. Without a requisition, separate source IDs stay separate until individually reviewed; employer/title similarity never silently combines openings.

```sh
python3 scripts/review_discovery_queue.py --workspace "$WORKSPACE" --occurred-at "$NOW" ingest --input "$RUN/intake.json" --source indeed
```

An actually empty query uses an empty array and explicit `--source`; missing or failed queries must not be represented as empty successful queries. Source completeness still depends on the connector's actual pagination and coverage capabilities.
Intake/status output includes content-addressed `intake_batches`. For any `source_results` entry with `success: true` in delivery input, provide `intake_ids` identifying that scope's exact saved intake batches, timezone-aware `completed_at`, and `seen_records` equal to the combined source IDs in those batches. Missing, foreign, future, or mismatched intake evidence cannot advance a checkpoint. A recovery may reference its original saved intake; it must not claim a new query occurred. Partial results keep `success: false` and preserve the existing checkpoint.

For each item, read responsibilities and requirements, compare with approved profile evidence, apply only approved hard filters, and verify promising official postings/application routes. Review employer/title hints against canonical records and configured legacy/email history; hints never justify automatic suppression. Unknown salary, ambiguous geography, travel, or title alone must not become invented exclusions. Preserve prior user passes, rejections, and applied states when exact identity and decisive history support them.

Record one decision with the current revision returned by `next`:

```json
{
  "review_id": "review:<64-character hash returned by next>",
  "expected_revision": 1,
  "expected_context": "<approval-context fingerprint returned by next>",
  "decision": {
    "status": "qualifying",
    "rationale": "An individual, evidence-based responsibility and requirements assessment.",
    "evidence": ["https://example.org/careers/verified-role"]
  }
}
```

`decide --input <file>` accepts one such object or an array. Allowed outcomes are `qualifying`, `duplicate`, `excluded`, `non_match`, or `blocked`. Each requires individual rationale and source URLs. A duplicate additionally requires `existing_reference` and an `identity_resolution` explaining the verified match. Qualifying a title/employer match also requires `identity_resolution` explaining why it is a distinct opening or reconsideration.
Echo the `expected_context` from the read used for assessment. If profile or criteria files change before recording a decision, the decision is rejected under lock; read the current inputs and reassess before retrying.

Use `blocked` only after actual verification attempts. Include `reason_code` (`source_unavailable`, `posting_identity_ambiguous`, `location_conflict`, `application_route_unavailable`, or `history_unavailable`), `attempts` (each with URL, timezone-aware `checked_at`, and `result`), specific `next_action`, and future timezone-aware `retry_after`. Attempt results are `http_403`, `http_404`, `content_missing`, `conflicting_evidence`, `identity_unresolved`, `history_unavailable`, or `request_error`. Generic “verification pending,” “not selected,” or lack of review time is unreviewed work, not a verified blocker. Do not invent attempts to close a queue item.

Deliver all novel qualifying roles through `plan_discovery.py` using the existing approved assessment and evidence contract. Queue decisions supplement that validation; they do not replace it. The delivery script validates queue state under the workspace lock and links successful canonical job IDs. Interrupted delivery can be replayed safely through canonical deduplication. Changed source content or approved inputs reopen assessment; stale revisions cannot overwrite later review.

Report returned rows, unique review items, qualifying roles, duplicates, exclusions, nonmatches, actual blockers, and unreviewed counts separately. Link a complete numbered review report. A source with unfinished or blocked review cannot advance its checkpoint. A successful bounded recovery does not establish complete provider coverage or authorize schedule cutover.
