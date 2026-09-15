# Complete intake and resumable review

Use the installed plugin's `scripts/review_discovery_queue.py`. Set `State/config.json` `require_review_queue` to `true` for new and repaired discovery workspaces. A queue file also enables enforcement automatically. Keep the queue, full public source snapshots, and review evidence inside the private workspace.

At the start of every run:

```sh
python3 scripts/discovery_retrieval.py --workspace "$WORKSPACE" status
python3 scripts/review_discovery_queue.py --workspace "$WORKSPACE" --occurred-at "$NOW" --output "$RUN/pending.json" next
```

Resume actionable retrieval continuations and missing-description pointers alongside all returned queue items before unrelated expansion. A `--limit` only limits the displayed work batch; it never marks the remaining queue complete. Deliver reviewed qualifying items, then check retrieval and review `status` again. `can_expand_search` indicates that the review queue can accept new intake; it does not establish exhausted source coverage. If it is false, continue review work. When returned rows and actionable work are handled, acknowledged permanent Indeed or unstructured-provider limitations permit related refinement and independent supported board scopes without closing or removing the original incomplete scopes. Preserve unfinished work across context or time limits and report the run as partial.

Use the explicitly approved [geographic prefilter](retrieval.md#geography-before-detailed-fit-review) before detailed fit review. Full board rows remain in the accounting ledger; evidence-bound automatic exclusions need not each receive a fresh semantic assessment. `prefilter --dry-run` previews existing backlog handling; `prefilter` applies it. Missing or conflicting evidence remains review work.

Distinct source posting IDs remain separate even when they share an internal requisition. A legacy mixed-ID row blocks decisions and delivery until repaired: `plan-recovery` produces a queue-hash-bound plan; `recover --input <plan.json>` archives the complete original and creates separate unreviewed rows while retaining all intake observations and receipts. Recovery never inherits a decision or canonical job link across posting IDs.

If retrieval status reports a normalization replay, use the saved scope's `replay` command. Earlier parser receipts and native responses stay immutable; corrected descriptions receive additive evidence and reopen affected review. Existing valid pointer resolutions retain their decisions. A conflicting newer observation requires explicit reconciliation instead of replacing it with recovered older text.

For new provider queries, follow [accounted source retrieval](retrieval.md): register the full currently known plan before the first request, register additional queries before execution, and immediately capture each entire native response with `discovery_retrieval.py`. It automatically ingests **every complete returned listing**, including likely repeats and nonmatches, and keeps missing-description records pending for retrieval. Supported provider responses must not be reconstructed as selected intake arrays. For unsupported sources, first capture the untouched native response using `provider: unstructured`, then capture all identified records in the documented extraction envelope with the original `raw_response`; its coverage remains incomplete. A partial board inventory still requires preserving every returned row.

Direct queue intake remains available for explicit legacy/recovery imports whose original evidence is already saved; it does not establish source retrieval completeness. Input is an array of objects containing `source`, `source_record_id`, `employer`, `title`, `location`, `posting_url`, optional `requisition_id`, optional `raw_field_hash`, and `raw` with the full source `description` and available terms. Preserve the same raw hash and source ID used by delivery. Distinct known requisitions remain distinct. Without a requisition, separate source IDs stay separate until individually reviewed; employer/title similarity never silently combines openings.

```sh
python3 scripts/review_discovery_queue.py --workspace "$WORKSPACE" --occurred-at "$NOW" ingest --input "$RUN/intake.json" --source indeed
```

An actually empty query uses an empty array and explicit `--source`; missing or failed queries must not be represented as empty successful queries. Source completeness still depends on the connector's actual pagination and coverage capabilities.
Intake/status output includes content-addressed `intake_batches`. For any `source_results` entry with `success: true` in delivery input, provide `coverage_scope_ids` identifying the exact completed retrieval scopes, `intake_ids` identifying their exact saved intake batches, timezone-aware `completed_at`, and `seen_records` equal to the combined source IDs in those batches. Missing, foreign, stale, future, or mismatched retrieval/intake evidence cannot advance a checkpoint; neither can an omitted registered query, capped result, unfinished page, or unresolved pointer. A recovery may reference its original saved evidence; it must not claim a new query occurred. Partial results keep `success: false` and preserve the existing checkpoint.

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

Report returned rows, unique source records, actual unique review items, qualifying roles, duplicates, exclusions, nonmatches, actual blockers, and unreviewed counts separately from planned/registered retrieval scopes, advertised provider totals, pending pages, and missing descriptions. Include exploratory requests in returned counts. Source IDs, review items, and identity-reconciled opportunities are distinct counts: multiple source records may share a review item or opening. Link a complete numbered review report. A source with unfinished retrieval or blocked/unreviewed listings cannot advance its checkpoint. Review completion is independent of provider coverage; a successful bounded recovery does not establish exhaustive discovery or authorize schedule cutover.
