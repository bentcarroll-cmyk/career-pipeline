# Accounted source retrieval

A completed review batch does not establish that a search retrieved every result. Use `scripts/discovery_retrieval.py` to track declared queries, full provider responses, continuations, and missing descriptions independently from listing assessments. It stores a locked ledger in `State/discovery-retrieval.json` and content-addressed raw snapshots in `Sources/discovery-retrieval/` inside the private workspace.

## Geography before detailed fit review

Complete board inventory and detailed review are different stages. Keep the entire native response, then use the approved geographic intake filter to account automatically for nonlocal-only postings. The optional `discovery_location_scope` in the hash-approved structured criteria enables `exclude_nonlocal_without_remote_option` only after explicit user confirmation. It defines `local_labels`, `exception_labels` for commute review, `broad_labels` for uncertain country-wide scopes, and `user_confirmed: true`. Do not embed a particular user's geography in the plugin or enable this policy by default. An absent policy preserves existing review behavior.

Capture still stores every complete posting and receipt. Automatic exclusions retain their exact location evidence, description hash, matcher version, source snapshot, revision, and approval context. Only retained/uncertain listings need detailed responsibility review. Any remote option, approved local alternative, missing or conflicting location information, or visible description omission keeps the posting for review. Remote retention does not establish state eligibility. Changed content, criteria, or matcher semantics requires reassessment; exclusions are never silent deletion.

For already captured work, preview `review_discovery_queue.py --workspace "$WORKSPACE" --occurred-at "$NOW" prefilter --dry-run`, then apply `prefilter`. Existing manual decisions are not silently rewritten. Use the returned counts to distinguish board rows, geographic exclusions, and remaining detailed reviews. Titles and undisclosed salaries are not geographic filters.

## Declare the work before requests

At the start of a run, inspect both retrieval and review status. Resume actionable outstanding pages, uncaptured registered requests, unresolved description pointers, and review decisions before adding unrelated searches. Permanent limitations such as Indeed's missing pagination remain recorded, but do not require an endless retry loop or prohibit related refinement and independent supported board scopes after the returned rows and actionable work are handled.

```sh
python3 scripts/discovery_retrieval.py --workspace "$WORKSPACE" status
python3 scripts/review_discovery_queue.py --workspace "$WORKSPACE" --occurred-at "$NOW" next
```

Register the full currently known run plan before sending the first request: every planned query, board, and exploratory probe, including known diagnostic and changed-filter variants. Do not register and execute only a prefix of that plan. Register newly discovered queries or boards before their own requests. Registration is idempotent for the same run, source, provider, and query. An unattempted registration remains pending; it cannot be represented by an empty result from another query. Report planned and registered scope counts so a planned query cannot silently disappear before registration.

```sh
python3 scripts/discovery_retrieval.py --workspace "$WORKSPACE" --output "$RUN/scope.json" register \
  --run-id "$RUN_ID" --source indeed --provider indeed --query "$RUN/query.json"
```

`query.json` contains the exact native search arguments. Keep the returned `scope_id` for capture and recovery. Use the CLI's current UTC default for new events. Supply `--occurred-at` only for the actual original timezone-aware event timestamp when replaying evidence; never invent future times or reuse a guessed run-end time for earlier captures.

## Capture every native response immediately

Preserve the entire native JSON response, including unabridged `structuredContent`, job objects, counts, and continuation fields. Immediately capture it against its registered scope before selecting candidates or requesting another page. Do not handwrite a reduced array, copy selected results, or discard an exploratory response because a later query looks better.

```sh
python3 scripts/discovery_retrieval.py --workspace "$WORKSPACE" capture \
  --scope-id "$SCOPE_ID" --input "$RUN/native-response.json"
```

The command saves raw evidence before parsing and automatically ingests every row with complete review fields. Missing-description rows remain durable retrieval pointers. Malformed provider responses also remain saved and actionable; a nonzero exit requires inspecting the returned error and scope. An empty valid provider page, a failed request, and an unattempted query are distinct states.

The current Indeed connector exposes no pagination or exhaustion contract. Treat it as supplementary discovery even if its advertised count equals the returned count. If it returns ten of 840, retain all ten and the unresolved coverage limitation; do not claim the other results were assessed. Once returned rows and actionable work are handled, narrower queries and independent supported boards can add coverage. Register them separately and retain the original capped scope as incomplete. Never invent a cursor, repeat the same capped call as if it were pagination, or label a response complete because all returned rows were reviewed.

## Other enabled sources and extracted pointers

For web search, enabled Firecrawl/browser/USAJOBS, or another native response without a supported provider parser, register the exact source request with `--provider unstructured` and the configured `--source` name. Immediately capture the untouched arbitrary JSON response using the same `capture` command. Its returned count is unknown and its coverage remains explicitly incomplete; saving opaque evidence is not a successful empty search.

After preserving that response, identify every visible listing and capture an envelope in the same scope:

```json
{
  "raw_response": {"content": "The complete original native JSON response goes here without omissions."},
  "extracted_listings": [
    {
      "source": "public_web",
      "source_record_id": "https://example.org/careers/role-123",
      "employer": "Example Employer",
      "title": "Operations Lead",
      "location": "Remote US",
      "posting_url": "https://example.org/careers/role-123",
      "raw": {}
    }
  ]
}
```

Replace `raw_response` with the entire original response object, not a summary or excerpt. Use the provider's stable listing identity when available; otherwise retain the exact original posting URL as the source record identity. Include `raw.description` only when the full description was actually captured. Complete records are ingested automatically; URL/title records without a description become durable pointers that `resolve-pointer` can later complete. An extraction envelope requires `raw_response` and cannot masquerade as a native Greenhouse, Lever, or Ashby response.

An unstructured scope never proves source exhaustion, even after every extracted record is resolved. Continue to report the unknown coverage and preserved native evidence. If the result identifies a supported ATS board, independently register and collect that board while retaining the original unstructured scope.

## Retrieve complete supported board scopes

Use the supported collectors for public Greenhouse, Ashby, and Lever boards. A board query contains `board` (the provider's board token) and `employer` (the actual employer). Lever optionally accepts `page_size` (1–100, default 100) and `region: "eu"` for an explicitly verified European board; its default region is `"us"`. Verify the board identity before registering it. The collector permits only its fixed documented HTTPS provider hosts, uses timeouts, and never sends credentials.

These collector requests are board-wide. They reject unsupported location, remote, salary, title, or other query fields instead of silently ignoring them. Do not describe these requests as provider-filtered searches. Smaller Lever pages change transport batch size, not eligibility or completeness. Local geographic exclusions happen after durable capture and before detailed review.

```sh
python3 scripts/discovery_retrieval.py --workspace "$WORKSPACE" --output "$RUN/board-scope.json" register \
  --run-id "$RUN_ID" --source public_ats --provider greenhouse --query "$RUN/board-query.json"
python3 scripts/discovery_retrieval.py --workspace "$WORKSPACE" collect --scope-id "$BOARD_SCOPE_ID"
```

`collect` follows supported provider continuation until exhaustion. It durably captures each page before requesting the next. A full Lever page requires another request; a short or empty supported terminal page closes pagination. If a later request fails, the prior pages and saved continuation remain intact. Re-run `collect` with the same scope ID to resume. Re-running a completed scope performs no new request. Invalid responses, non-progressing cursors, or unresolved description pointers return nonzero with actionable incomplete state.

Do not substitute a search-engine health check for board collection. Search results that identify actual postings must remain accounted for even when the full board is unavailable. Retrieve the corresponding supported provider scope and full posting fields; retain any remaining URL/title pointers as unresolved work. A whole-board inventory is not a prerequisite for preserving or reviewing the complete listings already returned.

## Resolve pointers and failures

For a missing-description pointer, fetch the exact official posting and save a complete intake record: `source`, the original `source_record_id`, `employer`, `title`, `location`, `posting_url`, optional `requisition_id`, and `raw` containing the full source description and observed terms. Bind it explicitly to its scope and original identity:

```sh
python3 scripts/discovery_retrieval.py --workspace "$WORKSPACE" resolve-pointer \
  --scope-id "$SCOPE_ID" --source-record-id "$SOURCE_RECORD_ID" --input "$RUN/full-record.json"
```

Do not fabricate descriptions or suppress a pointer by rejecting its title. When fetching the full posting for a known pointer fails, `fail` must include its original `--source-record-id` so the failure remains attached to that pointer and clears when the pointer is successfully resolved. This is required even if the source also has unfinished pages or a permanent supplementary coverage limitation.

```sh
python3 scripts/discovery_retrieval.py --workspace "$WORKSPACE" fail \
  --scope-id "$SCOPE_ID" --source-record-id "$SOURCE_RECORD_ID" \
  --reason "$OBSERVED_ERROR" --next-action "$RECOVERY_ACTION"
```

For a board page or native search request failure before a response is available, omit the pointer ID and record the observed error and concrete recovery action:

```sh
python3 scripts/discovery_retrieval.py --workspace "$WORKSPACE" fail \
  --scope-id "$SCOPE_ID" --reason "$OBSERVED_ERROR" --next-action "$RECOVERY_ACTION"
```

Resolving a pointer clears its actionable fetch failure; it does not establish exhaustion of the source or clear an independent page failure.

### Conflicting captures with the same timestamp

If replay reports `capture_time_conflict`, different versions of the same posting have equal capture timestamps and their order is uncertain. Both snapshots, intake receipts, and the prior review decision remain saved. The posting is held for fresh evidence; review decisions, delivery, and source completion cannot resolve the conflict by reusing the prior assessment.

Register a new scope in a new run for the same board or source query, then fetch and capture the posting again using its actual, strictly later capture timestamp. Do not retimestamp an old response or repeat a saved replay as if it were a fresh observation. This later capture may confirm either previous body; it clears the conflict and reopens the posting for review, while retaining the earlier decision and conflict evidence in history. Replaying the older captures afterward preserves the resolved state. The pending entry identifies the posting, review ID, and conflicting timestamp.

## Search quality and completion

Use approved responsibility families and geography/work-model constraints to form focused queries. Apply upstream hard filters only when the user's approved criterion and the provider's semantics establish a safe exclusion. Preserve unknown compensation, ambiguous geography, or unverified travel for review. A minimum-salary query must not become the only path for roles whose salary is undisclosed or whose range crosses the approved floor. Title similarity and a tool's first-page ranking never replace responsibility review.

For a `source_results` entry with `success: true`, include `coverage_scope_ids` for the exact completed retrieval scopes, their reconciled `intake_ids`, all `seen_records`, and timezone-aware `completed_at`. Provider-supported exhaustion, intact saved responses, no omitted relevant scopes, and no unresolved pointers are mandatory in addition to review completion. Partial or legacy batch-only evidence cannot advance the checkpoint. An absent ledger means unknown retrieval coverage, not complete coverage.

Report source scopes separately from review items: planned/registered/attempted/exhausted/pending scopes; source-reported totals and returned rows; ingested rows and unresolved pointers; review decisions and remaining reviews. Count all actual requests, including probes. Label distinct source IDs as unique source records, use the actual queue count for unique review items, and reserve unique opportunities for identity-reconciled openings. Multiple source records may share a requisition and review item. Advertised totals across overlapping queries must not be summed and presented as distinct jobs.

Supported exhaustion proves accounting within the declared board/query scope. It does not prove exhaustive coverage of the internet or recover hidden Indeed results. Keep that coverage boundary visible while delivering reviewed qualifying matches and preserving remaining work.
