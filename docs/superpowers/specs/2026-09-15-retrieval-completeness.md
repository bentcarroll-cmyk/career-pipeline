# Retrieval completeness repair

The user approved implementation of the September 15 discovery audit fixes.

## Requirements

- Python >=3.11; standard library only. Preserve unrelated worktree edits.
- A reviewed batch is not a completed search. Missing retrieval evidence must fail closed.
- Persist every planned query/board, complete raw response, returned listing, missing-description pointer, and unfinished continuation before selecting promising jobs.
- Register the entire known query plan before the first request; additional queries and probes are registered before their execution. No machine can discover an omitted external tool call whose existence was never recorded.
- Provider results, not caller-written success flags, establish retrieval exhaustion. Indeed's current connector has no continuation contract and is supplementary, never proof of exhaustive coverage even when an advertised approximate total matches.
- Implement public Greenhouse and Ashby complete-board retrieval and Lever pagination. Fetch only fixed documented HTTPS provider hosts; validate board tokens, use timeouts, reject cross-host redirects, and never pass credentials.
- Retain malformed responses and failures as actionable incomplete scopes. No silent skips, fabricated descriptions, or truncation to fit a processing limit.
- Support replay/resumption, content-addressed response evidence, duplicate-page detection, and lock-protected state. A partially completed run may deliver reviewed matches but must preserve all remaining work.
- Missing-description rows remain pending retrieval tasks until a full-description intake is explicitly linked; an empty successful response is different from an unattempted source.
- Successful source checkpoints require completed retrieval scopes and exact reconciled intake receipts. Omitted registered queries, omitted records, stale scopes, foreign scopes, malformed pages, changed totals, or remaining cursors prevent completion.
- Legacy review queues remain readable and reviewable. Their batch-review status may be complete, but source/discovery completeness is unknown until supported retrieval evidence exists.
- Existing source checkpoints and canonical application history are not reset. No external publication, applications, messaging, or new job-search campaign.

## Interfaces between workers

`career_pipeline.source_pages.parse_page(provider, response, *, query, cursor=None)` returns a dict:

```python
{
    "records": [intake_record],  # raw includes full description when available
    "reported_total": 840,       # int or None, not a distinct-job-market count
    "exhausted": False,
    "next_cursor": None,         # string or None
    "limitations": ["provider_has_no_pagination"],
}
```

Every valid provider job object produces one record, including pointers lacking required review fields. `source_record_id` is stable provider ID (Indeed jrtk); raw includes original provider fields plus normalized description. Parser raises on malformed top-level payload, malformed rows, duplicate IDs within a page, count contradictions, or invalid cursor. The caller persists original response before parsing. For board providers query contains `board`, `employer`, and Lever `page_size` (default 100). The ledger overwrites record `source` with its registered source. Ashby `isListed=false` remains accounted for but cannot be automatically published as a qualifying job.

Provider `unstructured` preserves unsupported native web/browser/other connector JSON responses as non-enumerable supplementary scopes. Its raw response is captured immediately, before extraction. A later explicit envelope `{"raw_response": original_response, "extracted_listings": [intake_record]}` retains the original response and any extracted complete listings or partial pointers. An envelope with extracted listings requires the full raw response. Source-local IDs may use the exact posting URL when the provider offers no stable identifier. Counts are explicitly unknown/lower bounds, never zero-result or exhaustion claims. Repeated extraction chunks must contain new rows, not silently skip duplicates. The same native response can be replayed idempotently. Unstructured captures always remain non-exhaustive even after all extracted pointers are resolved; they do not qualify as complete ATS source evidence.

`career_pipeline.collectors.fetch_board_page(provider, *, query, cursor=None, fetch_json=None)` returns the original JSON response. `fetch_json(url)` is an injectable network boundary for tests. It does not persist files; the CLI captures each result immediately before requesting another page. Fixed hosts: boards-api.greenhouse.io, api.ashbyhq.com, api.lever.co, api.eu.lever.co (explicit regional query setting only). Page shape/exhaustion is determined by `parse_page`.

`career_pipeline.retrieval` owns `State/discovery-retrieval.json` and raw snapshots under `Sources/discovery-retrieval/`:

```python
register_scope(workspace, *, run_id, source, provider, query, now) -> dict
capture_response(workspace, scope_id, response, *, now, cursor=None) -> dict
record_failure(workspace, scope_id, *, now, reason, next_action, source_record_id=None) -> dict
resolve_pointer(workspace, scope_id, *, source_record_id, record, now) -> dict
load_ledger(workspace) -> dict
summary(workspace, *, now) -> dict
validate_source_result(workspace, source, result, *, now) -> None
```

Registration is idempotent for identical run/source/provider/query. Returns a row containing `scope_id`, source, provider, query, run_id, retrieval status, next_cursor, pages and unresolved pointers. Raw captures are immutable and hash-checked. Each capture automatically ingests ALL complete-description records through review_queue.ingest, persisting resulting intake IDs; incomplete records stay scope pointers. Capture replay repairs an interrupted ingestion without duplicating observations or losing evidence. A later registered scope cannot silently remove an earlier open scope. Registered source aliases may use provider `greenhouse`, `lever`, `ashby`, or `indeed`; `public_ats` aggregates the three board sources.

An additive `replay_scope(workspace, scope_id, *, now)` audits raw evidence and replays any captured-but-not-ingested pages or pointer resolutions before another network request. CLI collection never trusts cached completion flags. Invalid extra captures remain unresolved; only explicitly provenance-linked supported retries can replace failed attempts without erasing evidence.

Known pointer-fetch failures explicitly name `source_record_id`, including on non-enumerable sources and before board pagination finishes. Successfully resolving the targeted pointer clears its actionable failure while retaining failure history and any independent page-continuation limitation.

Summary includes `complete`, `status` (unknown/incomplete/complete), `scopes`, actionable `pending`, `unresolved_pointers`, and returned/ingested accounting. No-ledger state is unknown, not complete. Scope completeness is retrieval exhaustion AND every returned record linked to an intake or an explicitly supported non-public disposition. Review completion is checked separately.

Source result payload adds `coverage_scope_ids`. Guard requires the exact scopes from the latest registered run for that source, no unresolved earlier scopes for the source, supported exhaustion, valid response snapshots, matching intake IDs and seen IDs, and capture time <= source completion time. Existing review/delivery checks still apply. Closed older runs need not be included in each new receipt union. Registration sequence is persisted explicitly rather than inferred from JSON object order. Missing enabled-source scopes in the current run prevent aggregate discovery completeness while independent completed source checkpoints remain possible. Existing checkpoint `cursor` can remain rotation metadata; actual retrieval continuation lives in each scope's `next_cursor`.

## Acceptance examples

1. Indeed advertises 840 and returns ten; all ten review decisions exist. `review_complete` may be true, `complete` and `retrieval.complete` are false, and a source-success payload cannot advance a checkpoint.
2. Nine scopes registered but eight responses captured: ninth scope remains pending, even if the other scopes have no pending reviews.
3. A page contains a job URL/title but no description: raw response is saved and a pointer remains pending; it cannot vanish through failed normalization.
4. Lever page 0 succeeds, page 100 fails: page 0 is already durable, source remains incomplete, retry begins at 100, and repeated pages/cursors do not count as progress.
5. An exact full Lever page requires another request; only an empty/short supported terminal page can exhaust it, with unique IDs reconciled.
6. Greenhouse `meta.total` mismatch, count changes, missing jobs key, malformed object, duplicate IDs, and raw snapshot tampering cannot produce completion.
7. A completed declared board scope may checkpoint after all of its returned records are reviewed and linked. Legacy batch-only intake cannot.

## Operational boundary

This repair guarantees accounting within tracked source scopes, not exhaustive coverage of the internet or hidden Indeed results. Direct connector calls still require the agent to register each query and immediately persist the native response; the CLI provides the enforced path, and instructions must prohibit bypassing it.
