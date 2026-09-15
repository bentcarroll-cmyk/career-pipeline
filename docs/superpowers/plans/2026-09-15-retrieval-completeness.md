# Retrieval Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent lost discovery work and false source completion, with complete-board collectors and resumable query accounting.

**Architecture:** A separate retrieval ledger records source scopes and raw pages before queue ingestion. Provider-specific parsing establishes exhaustion; review queues and checkpoints consume that evidence rather than caller claims.

**Tech Stack:** Python >=3.11, standard library, unittest, existing atomic persistence and workspace locks.

**Completion:** Implemented and independently reviewed. All 130 focused tests pass; full-suite snapshot has three unrelated application/PDF-packaging failures. See `docs/reviews/2026-09-15-retrieval-completeness.md` for verification and deployment boundaries.

**Spec:** `docs/superpowers/specs/2026-09-15-retrieval-completeness.md`

## Global Constraints

- Python >=3.11; standard library only. Preserve unrelated worktree edits.
- Existing source checkpoints and canonical application history are not reset. No external publication, applications, messaging, or new job-search campaign.
- Write regression tests first and observe RED before production edits. Do not commit, stage, or publish other workers' changes.
- Use a Python >=3.11 runtime for tests; set `PYTHONPATH=src`.

### Task 1: Durable retrieval ledger and completion gates

**Files:** Create `src/career_pipeline/retrieval.py`, `tests/unit/test_retrieval.py`; modify `src/career_pipeline/review_queue.py`, `src/career_pipeline/checkpoints.py`, `scripts/plan_discovery.py`, and affected checkpoint/review/delivery tests.

**Interfaces:** Consume `source_pages.parse_page`; produce all retrieval functions in the spec. Add `coverage_scope_ids: tuple[str,...] = ()` as the final SourceResult field; preserve positional callers. Review summary exposes `review_complete` for old semantics, `retrieval` for scope status, and `complete` only when both are complete. Review work and independent source collection remain resumable even with capped sources unresolved.

- [x] Write failing tests for 10/840, missing ninth query, pointer retention, invalid/tampered receipts, empty versus absent source, retry after ingestion interruption, replay, source-success bypass and legacy unknown completeness. Minimal regression assertion:
  ```python
  self.assertFalse(summary(workspace, now=NOW)["complete"])
  with self.assertRaisesRegex(ValueError, "retrieval"):
      validate_delivery(workspace, success_payload, now=NOW)
  ```
- [x] Run `python3 -m unittest discover -s tests/unit -p test_retrieval.py -v`; record expected failures.
- [x] Implement registry, capture-before-parse/ingest, pointer resolution, integrity checks and source-result validation under existing reentrant workspace locks. Guard public delivery/merge entry points before writes; no reliance on optional enable flags for success claims.
- [x] Adjust legacy tests to assert review-only completion explicitly; add genuine complete provider captures for tests that assert source checkpoint advancement. Do not mock away the new guard to make tests pass.
- [x] Run focused retrieval, checkpoint, queue and discovery delivery tests; self-review and return red/green evidence.

### Task 2: Provider-shaped parsing and board acquisition

**Files:** Create `src/career_pipeline/source_pages.py`, `src/career_pipeline/collectors.py`, `tests/unit/test_source_pages.py`, `tests/unit/test_collectors.py`; modify existing board normalizers only if strict malformed-row handling is needed, with tests.

**Interfaces:** Implement `parse_page` and `fetch_board_page` exactly as specified. No dependency on the retrieval ledger. Original full responses cross this boundary, never a selected subset.

- [x] Write provider-shaped failing tests: Indeed totals and no pagination; Greenhouse complete and total mismatch; Ashby published/private postings and absent descriptions; Lever full/short/empty pages and all description sections. Test malformed rows cannot silently disappear.
- [x] Run `python3 -m unittest discover -s tests/unit -p test_source_pages.py -v` and collector tests; record RED.
- [x] Implement strict parsers with pointer retention. Fetch supported board endpoints using URL-encoded validated board tokens, no filters or arbitrary URLs; use timeouts and redirect safety. Raise on failed HTTP/JSON; the ledger caller owns durable failure recording.
- [x] Assert emitted endpoints with a deterministic network fake and correct page requests. Include no network call for invalid token, size, provider or cursor.
- [x] Run focused tests, self-review and return red/green evidence plus verified official API references.

### Task 3: Supported CLI workflow and operator instructions

**Files:** Create `scripts/discovery_retrieval.py`, `tests/integration/test_retrieval_cli.py`, `skills/discover-jobs/references/retrieval.md`; modify `skills/discover-jobs/SKILL.md`, references `source-routing.md`, `review-queue.md`, `skills/onboard/assets/discovery-automation-prompt.md`. Add schema/documentation if needed, without touching release version files.

**Interfaces:** CLI calls retrieval functions from Task 1 and fetcher from Task 2. Global `--workspace`, optional `--occurred-at` defaults to real UTC clock, optional `--output`. Commands: register (`--run-id --source --provider --query` JSON file), capture (`--scope-id --input` raw native response JSON, optional `--cursor`), collect (`--scope-id` loops all pages persisting before next), status, fail (`--scope-id --reason --next-action`), resolve-pointer (`--scope-id --source-record-id --input`). Errors are JSON stderr/nonzero. collect records observed failure with actionable continuation and returns nonzero, never successful partial completion. Replaying capture is supported; repeated collect of exhausted scope is a no-op.

- [x] Write CLI tests that run subprocesses in temporary workspaces: register/capture/status 10-of-840 shows partial and all ten ingested; missing-description pointer remains pending; bad input produces structured error; no declared scope is silently created after capture; registered-unattempted scope remains pending.
- [x] Run tests and record RED before implementation.
- [x] Implement CLI and error handling. A bounded optional page budget, if offered, must leave a resumable pending cursor and return explicitly partial, not complete.
- [x] Update instructions: register every query before native tool calls; immediately capture the entire structured response; no handwritten selected arrays; use board collectors; retrieve pointers even when board coverage is incomplete; source-success requires coverage_scope_ids; report source scopes separately from reviewed jobs; keep Indeed supplementary; preserve real timestamps.
- [x] Run CLI tests and packaging validation; self-review and return red/green evidence.

### Task 4: Integration, independent review and handoff

**Files:** Integration tests, plan progress record, release documentation as appropriate.

- [x] Run complete suite with `python3 -m unittest discover -s tests -q`.
- [x] Independently review code against the seven acceptance examples, especially concurrency, crash replay, omitted scopes and bypass paths.
- [x] Fix review findings with focused regression tests; rerun complete suite and plugin/privacy validators.
- [x] Package locally if valid; do not publish remotely. Clearly distinguish source implementation, install status, historic intake repair and unavoidable upstream coverage limitations in handoff.
