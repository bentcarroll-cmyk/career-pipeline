# Pre-push fixes implementation plan

> **For agentic workers:** Use the existing review reproductions, test each failure before fixing it, and execute only the assigned files. The user authorized implementation in the current task.

**Goal:** Fix all five defects in the pre-push product review without losing existing evidence or weakening delivery checks.

**Architecture:** Preserve immutable captures and receipt history. Guard the active view against older observations, recognize equivalent broad location labels, and add a supported path for legacy packet revalidation. Keep changes within existing modules.

**Tech Stack:** Python 3.11+, unittest, optional PDF runtime, local JSON records.

**Spec:** `docs/reviews/2026-09-15-pre-push-product-review.md`.

## Constraints

- Preserve the existing uncommitted candidate and private workspaces.
- Use temporary synthetic workspaces for regressions and verification.
- Do not change Git branch/index/history or publish as part of these fixes.
- No new core dependencies; retain final-PDF measurement and immutable history.

## Discovery queue recovery

**Owner/files:** discovery agent; `src/career_pipeline/review_queue.py`, retrieval integration if needed, `tests/unit/test_review_queue.py`, `tests/unit/test_retrieval.py` and related retrieval integration tests.

- [x] Add and run failing regressions for interrupted old page/pointer replay after newer reviewed content, and a legacy URL A -> B -> A round-trip.
- [x] Keep older capture evidence and intake receipts while preserving newer active content, decisions, and monotonic timestamps.
- [x] Retain a matching observation when identical snapshot bytes require a different content-hash version; verify replay remains idempotent.
- [x] Run the queue/retrieval regression suites and report results.

## Geographic intake

**Owner/files:** location agent; `src/career_pipeline/location_prefilter.py`, `tests/unit/test_location_prefilter.py`, `tests/unit/test_review_location_prefilter.py`.

- [x] Add and run failing regressions for `United States (US)` and `USA, United States`, including real queue intake and stale matcher decisions.
- [x] Retain equivalent compound broad labels without weakening exclusion of concrete nonlocal cities.
- [x] Update matcher semantics version so old false exclusions reopen through normal reevaluation.
- [x] Run location and queue-prefilter tests.

## Legacy application packets

**Owner/files:** packet agent; `src/career_pipeline/packets.py`, `scripts/update_packet.py`, packet tests, and packet recovery instructions.

- [x] Add a failing real-PDF regression for a valid legacy saved packet missing layout evidence.
- [x] Implement an explicit audited revalidation path that preserves original receipts and final-PDF hash bindings.
- [x] Verify same-version delivery, persistence/retry behavior, and rejection of changed files, failed measurements, and conflicting audit evidence.
- [x] Document the supported recovery command and run packet/resumption tests.

## Resume identity

**Owner/files:** coordinator; `src/career_pipeline/quality.py`, `tests/unit/test_quality.py`, `tests/integration/test_resume_identity_check.py`.

- [x] Add failing tests for legitimate work-history titles under conventional headings and prohibited titles wrapped over lines.
- [x] Bound the header scan at conventional sections; join wrapped header text without extending the scan into work history or matching generic title fragments.
- [x] Run unit and CLI tests, including positive/negative controls.

## Integration and completion

- [x] Independently review the final changes and resolve actionable findings.
- [x] Run the full suite from a clean candidate snapshot; validate environment, compilation, plugin, package, privacy, and checksum.
- [x] Update the review note with remediation evidence and test results; summarize the outcome to the user.

## Completion evidence

- All five findings resolved; independent review also identified and verified the equal-timestamp conflict hold and recovery path.
- 471 tests passed in a clean candidate; compilation, environment, source/archive privacy, package validation, and checksum checks passed.
- See the updated pre-push product review for behavior changes, regression coverage, package hash, and operational limits.
