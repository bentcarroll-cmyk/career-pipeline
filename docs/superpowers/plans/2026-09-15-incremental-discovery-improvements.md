# Incremental Discovery Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans when implementation is separately authorized. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make twice-daily discovery surface every qualifying new or meaningfully changed opportunity promptly, without repeatedly assessing unchanged postings or hiding incomplete retrieval.

**Architecture:** Preserve complete source captures, then perform inexpensive identity, change, and approved eligibility checks before detailed assessment. Maintain progress independently for each board/query, reuse valid prior decisions, and retain a broader periodic coverage sweep.

**Tech Stack:** Existing Python >=3.11, standard-library collectors, unittest, local JSON records, content-addressed evidence, and locked atomic persistence.

**Spec:** The recommendations and acceptance criteria in this document capture the September 15, 2026 discussion. Read alongside [the retrieval-completeness design](../specs/2026-09-15-retrieval-completeness.md) and current discovery skill references. This is a future-work guide, not a finalized API or migration specification.

**Status:** Proposed; not implemented by creating this document. The user requested a durable guide for later work. That request does not authorize installation, schedule changes, history imports, a new search, or application actions. Reconfirm the implementation scope before execution.

## Global constraints

- Complete the current repair/baseline work before switching to the proposed operating model. Do not abandon existing unreviewed rows, unresolved pointers, or undelivered qualifying roles.
- Preserve every returned source record and its evidence. A smaller transport or review batch must leave the remainder explicitly pending, never silently discarded.
- Recent-only filtering is an optimization, not a new eligibility requirement. An unseen older or undated opening can still qualify.
- Keep deduplication. Reposts, overlapping searches, and alternate source URLs do not automatically represent new opportunities.
- Preserve applied states, exact user passes/suppressions, and prior decisions. A refreshed date does not reset them.
- Keep distinct public posting IDs distinct during intake, even when they share an employer's internal requisition. Link aliases only with verified identity evidence; do not undo the posting-identity repair.
- Only user-approved hard exclusions may remove roles from detailed assessment. Missing salary, ambiguous geography, and title alone are not exclusion grounds. Approved profile and criteria remain authoritative.
- Keep the existing evidence-bound geographic filter: exclude nonlocal-only postings with no remote option in the full captured description; retain approved commute exceptions, remote options, missing information, and conflicts. Remote retention does not prove state eligibility.
- A capped/failed source remains partial. Progress on an independent complete board must not erase another source's coverage gap.
- No automatic applications, packet preparation, outreach, external exports, or new connector enablement. Preserve current user-selected schedule/model settings until separately authorized.
- Keep private source snapshots, application history, and candidate information in the configured private workspace, never in release assets or test fixtures.
- Preserve unrelated worktree changes. Use synthetic/provider-shaped fixtures and test migrations on temporary workspace copies before live changes.

## 1. Starting point observed on September 15, 2026

These are dated implementation observations, not guarantees about a future checkout. Reinspect before executing.

| Area | Existing behavior | Improvement needed |
| --- | --- | --- |
| Review reuse | An unchanged exact posting can retain its assessment; changed content or approval context reopens review. | Avoid reopening solely for provider refresh metadata; retain meaningful-change detection. |
| Content comparison | `_content_hash` excludes Indeed's `posted_date`, but retains ATS fields such as `updated_at` and `publishedAt`. | Separate freshness observations from fields that affect eligibility, fit, identity, or application routing. |
| Board collection | Current Greenhouse/Ashby collectors fetch whole boards; Lever follows pages. Unsupported query filters are rejected. | Reduce repeated assessment first; add upstream filters only after verifying their actual semantics and coverage. |
| Indeed | The available search action has no date, pagination, or result-limit argument. | Keep supplementary; do not assume narrower keywords or “recent” text remove its ten-result limitation. |
| Operating guidance | Already specifies last-successful-checkpoint minus 48 hours, a seven-day initial query lookback, a no-date query, and a broader Friday pass. | Turn guidance into tested, source-aware behavior. The initial lookback is not permission to skip the existing baseline or older returned jobs. |
| Checkpoints | Validation is source-sensitive, but historical incomplete scopes within the same source can block later progress. | Add board/query-level progress and explicit reconciliation of historical gaps. |
| Queue order | Pending items are primarily ordered by oldest first-seen time. | Balance timely fresh opportunities with guaranteed progress on older pending work. |
| History | Canonical and legacy/application evidence must be reconciled before novel delivery. | Reuse a verified local identity mapping and refresh only relevant changed/ambiguous evidence. |

## 2. Recommended behavior

### Freshness means more than a posting date

Track these signals separately:

- **First seen:** When this system first captured the exact source posting.
- **First published:** Original publication time, only when the source supplies it with that meaning.
- **Last published/reposted:** Latest publication event, only when supported by source semantics.
- **Source updated:** Provider modification time; not necessarily a substantive job change.
- **Last seen / last verified:** Observation and availability checks performed by this system.
- **Material content version:** Changes affecting responsibilities, requirements, compensation, location/work model, employment type, eligibility, identity, or application route.

Preserve original provider values and normalize usable timestamps to timezone-aware values. Missing, malformed, or conflicting dates remain unknown; never substitute retrieval time and label it publication time.

The review decision should be:

| Observation | Required handling |
| --- | --- |
| Unseen exact posting, even with an old/missing date | Capture, apply approved filters, and assess if retained. |
| Known posting; unchanged material content and current criteria/profile | Record the observation and reuse its valid decision. |
| Known posting; timestamp-only refresh | Record the refresh without automatically repeating full fit assessment or notifying again. |
| Known posting; substantive change | Reopen the affected assessment and preserve prior evidence/decision history. |
| Known posting disappears and later returns | Reverify availability and identity; preserve prior application/user decisions. Reuse fit assessment if still valid. |
| New source URL/ID resembles an existing opportunity | Resolve identity conservatively; no employer/title-only automatic suppression. |
| Due verification retry or stale approval context | Resume/reassess explicitly; a recent-date window must not hide it. |

Use a 48-hour overlap before the last safely completed board/query checkpoint where date filtering is genuinely supported. A Monday run or recovery after an outage must cover the elapsed gap, not simply “the last 24 hours.” Incomplete work retains its original checkpoint and continuation. Track attempts separately from completeness; never advance a completed-coverage checkpoint merely because a request returned.

For whole-board APIs, collect the inventory and compare locally. Reading thousands of rows is different from performing thousands of fresh semantic assessments. Do not promise reduced network volume where the provider requires full-board responses.

### Proposed cadence, subject to later approval

Keep the current weekday 07:00 and 16:00 America/New_York run times unless the user changes them. The following changes the work mix, not the times:

- **Morning:** New/changed opportunities at priority employers plus the morning employer rotation; focused responsibility/location searches; deliver verified matches.
- **Afternoon:** New/changed opportunities plus the afternoon rotation and due verification retries; deliver additional verified matches without repeating unchanged notifications.
- **Friday morning:** Broader synonyms, employer discovery, an approximately 30-day supplementary query window, and date-unrestricted coverage checks for missed/undated openings.

Do not silently remove an existing required no-date query or employer group when adopting this split. Make any reduction in frequency explicit and approved. Weekly catch-up complements daily incremental processing; it does not justify dropping older returned records.

## 3. Implementation sequence

Each phase is independently reviewable. Before coding a phase, define its exact interfaces and migration contract, add failing regression tests for the cases below, observe the failures, implement the minimal change, and rerun the affected suites. Do not treat an unchecked phase as permission to execute it now.

### Phase A — Correct meaningful-change detection first

**Inspect/modify:** `src/career_pipeline/review_queue.py`, `src/career_pipeline/source_pages.py`.

**Tests:** `tests/unit/test_review_queue.py`, `tests/unit/test_source_pages.py`, `tests/integration/test_parser_replay_compatibility.py`.

- [ ] Define a versioned material comparison that preserves all eligibility/fit/identity/route evidence while separating documented volatile timestamps and tracking metadata. Unknown fields must not be silently discarded as irrelevant.
- [ ] Keep complete raw snapshots and freshness observations unchanged. Distinguish a metadata refresh from a substantive change in reports.
- [ ] Test timestamp-only `publishedAt` / `updated_at` changes: no new fit-review revision or duplicate notification when identity, material terms, and approval context are unchanged.
- [ ] Test changes to salary, responsibilities, requirements, remote/state eligibility, employment type, and application destination: each invalidates the relevant prior decision.
- [ ] Test old hash-version replay, A-to-B-to-A content history, changed criteria/profile, and distinct public posting IDs sharing an internal requisition.
- [ ] Migrate additively on a temporary workspace copy; do not rewrite immutable receipts or broadly clear decisions. Independently review evidence integrity before applying a live migration.

**Acceptance:** Metadata-only refreshes create zero unnecessary full fit reviews; material changes remain detectable and prior evidence remains verifiable.

### Phase B — Add safe board/query-level incremental progress

**Inspect/modify:** `src/career_pipeline/checkpoints.py`, `src/career_pipeline/retrieval.py`, `src/career_pipeline/collectors.py`, `src/career_pipeline/sources/base.py`.

**Tests:** `tests/unit/test_checkpoints.py`, `tests/unit/test_retrieval.py`, `tests/unit/test_collectors.py`, `tests/integration/test_retrieval_flow.py`, `tests/integration/test_retrieval_scope_queries.py`.

- [ ] Define progress keys including configured source, provider, employer board, and normalized query scope. Keep attempt, captured inventory, and completed coverage state distinct.
- [ ] Persist continuations and overlap boundaries per scope. Date-less/older unseen records and due unresolved work must survive any recent-query optimization.
- [ ] Test a completed board alongside a failed board and a capped Indeed scope: only the independently completed scope may advance.
- [ ] Test Friday-to-Monday continuity, multi-day outage recovery, interruption between pages, and replay of the same capture.
- [ ] Define evidence-backed historical-scope reconciliation. A later full inventory may resolve exact outstanding records, but cannot claim retrieval of an older posting that disappeared before capture; preserve that historical gap.
- [ ] Keep unsupported upstream filters rejected. Add native filters only with provider documentation, request-shape tests, and an explicit strategy for remote/secondary/unknown-location coverage.

**Acceptance:** One failed board does not force repeated full reassessment of other boards; no gap is closed by advancing a timestamp or deleting an old scope.

### Phase C — Reuse verified identity and history mappings

**Inspect/modify:** `src/career_pipeline/dedupe.py`, `src/career_pipeline/discovery.py`, existing canonical indexes, and the configured private legacy-history bridge.

**Tests:** `tests/unit/test_dedupe.py`, `tests/integration/test_cross_source_discovery.py`, `tests/integration/test_discovery_delivery.py`.

- [ ] Define a derived local lookup linking verified official posting identities, canonical jobs, proven source aliases, and exact historical references. Preserve public posting IDs separately from internal requisitions.
- [ ] Bind reusable history decisions to their evidence/version and refresh relevant changed or ambiguous evidence before delivery. Do not claim dated snapshots are current mailbox coverage.
- [ ] Test the same opening reposted or returned by multiple sources: one opportunity, preserved history, no repeated “new role” notification.
- [ ] Test two distinct postings sharing an internal requisition and two similar titles with different requisitions: neither is silently merged or suppressed.
- [ ] Test exact applied/passed roles versus a genuinely different role at the same employer; employer-only email must not suppress both.
- [ ] Verify cache rebuilds are lossless and unavailable history produces an explicit gap. Do not auto-import legacy opportunities or retain unrelated email bodies.

**Acceptance:** Routine duplicate checks use verified local evidence; only novel or ambiguous candidates require deeper history reconciliation.

### Phase D — Balance fresh matches, backlog progress, and delivery

**Inspect/modify:** `src/career_pipeline/review_queue.py`, `src/career_pipeline/discovery.py`, `scripts/review_discovery_queue.py`, `scripts/plan_discovery.py`.

**Tests:** `tests/unit/test_review_queue.py`, `tests/integration/test_discovery_delivery.py`, `tests/integration/test_retrieval_cli.py`.

- [ ] Propose and approve explicit scheduling rules for fresh opportunities, material changes, deadlines, and older pending work. Ranking affects order, never eligibility.
- [ ] Reserve continuing capacity for older pending work so new arrivals cannot starve it. Keep unknown-date items eligible.
- [ ] Permit independent fresh-source work alongside a separately tracked repair backlog only through a tested policy change; do not bypass the current queue-expansion guard ad hoc.
- [ ] Test bounded batches and interruptions: all unfinished rows remain queued with their original evidence; zero rows become “reviewed” merely because a batch ended.
- [ ] Deliver verified qualifying roles as they become ready, even if unrelated verification remains pending. Test idempotent delivery and notification recovery across interruption.
- [ ] Report missing evidence and due retries separately from work that simply has not been reviewed.

**Acceptance:** Fresh matches reach the user promptly, old pending work demonstrably progresses, and every qualifying role is delivered without a top-N cap.

### Phase E — Update operating guidance, validate, then authorize rollout

**Inspect/modify after approval:** `skills/discover-jobs/SKILL.md`, its retrieval/review/source-routing references, `skills/onboard/assets/discovery-automation-prompt.md`, and the configured private operating guide. Resolve the actual saved automation by ID before any approved change.

- [ ] Align the instructions with Phases A-D and remove contradictory dated operating-state text. Clearly distinguish current behavior from the proposed daily/weekly split.
- [ ] Preserve enabled/deferred/declined connector decisions, approved criteria, user-selected model settings, and action boundaries.
- [ ] Add run metrics: records captured; safe exclusions; decisions reused; new/materially changed items requiring review; unique qualifying roles delivered; discovery-to-delivery latency; repeated-review rate; oldest pending age; and per-board incomplete coverage.
- [ ] Measure against the repaired baseline before claiming savings. Do not set a claimed percentage reduction without observed data or optimize only for fewer retrieved jobs.
- [ ] Run relevant unit/integration tests and the full suite in the project's supported clean release-validation environment. Keep private workspace data out of the distributable and do not weaken privacy checks to make tests pass.
- [ ] Back up affected private state, test migration/replay on a copy, independently review changes, and document rollback before seeking installation/schedule approval.
- [ ] After approval, install and read back the intended version/configuration. Validate an actual native automation run; a normal-thread smoke test is not scheduled execution.
- [ ] Check both daily run types and the broader weekly path. Report remaining coverage limitations rather than declaring universal market completeness.

**Acceptance:** Measured reduction in repeated work, no missing-record regressions, verified scheduled execution, and explicit user approval for deployment changes.

## 4. Verification commands for later execution

Use the project's Python >=3.11 runtime, with `PYTHONPATH=src`. These commands are guidance for implementation; they were not run as part of creating this document.

```sh
PYTHONPATH=src python3 -m unittest tests.unit.test_review_queue tests.unit.test_source_pages tests.unit.test_checkpoints tests.unit.test_retrieval tests.unit.test_collectors tests.unit.test_dedupe -v
PYTHONPATH=src python3 -m unittest tests.integration.test_parser_replay_compatibility tests.integration.test_retrieval_flow tests.integration.test_retrieval_scope_queries tests.integration.test_cross_source_discovery tests.integration.test_discovery_delivery tests.integration.test_retrieval_cli -v
```

For full-suite and packaging/privacy verification, follow the current [release guide](../../releasing.md). Verify the selected interpreter and dependency availability first. Do not run a privacy scan over an intentionally private workspace and then mistake the resulting exposure warning for permission to include that workspace in a release.

## 5. Source semantics and references

Provider documentation was checked during the September 15 discussion; revalidate before adding provider-specific filtering:

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html): distinguishes job-post ID from internal-job ID; exposes update/publication metadata, and documents its public list endpoint.
- [Ashby public Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api): `publishedAt` means last publication; public board data includes remote, workplace, secondary-location, and optional compensation fields. Do not assume employer-authenticated sync APIs are available to this discovery plugin.
- [Lever Postings API](https://github.com/lever/postings-api): supports pagination and certain categorical filters; `workplaceType` is documented as not filterable. A location filter is not equivalent to complete remote eligibility coverage.
- [Discovery skill](../../../skills/discover-jobs/SKILL.md), [retrieval contract](../../../skills/discover-jobs/references/retrieval.md), and [review queue contract](../../../skills/discover-jobs/references/review-queue.md): preserve intake, evidence, partial coverage, and canonical delivery safeguards.

## 6. Resume checklist

- [ ] Read this guide and the current discovery contracts; verify which proposed phases have since been implemented.
- [ ] Inspect live repair/review/retrieval status and pending deliveries without assuming the September 15 baseline is complete.
- [ ] Confirm current installed/source versions, approved criteria, actual automation configuration, and outstanding unrelated worktree changes.
- [ ] Ask for authorization for the first unimplemented phase. Start with Phase A, then B; do not begin with a blanket “posted in the last day” cutoff.
- [ ] Keep the implementation, installation, private-state migration, and scheduled-validation outcomes distinct in the handoff.

The intended simplification is **less repeated judgment, not less accountable coverage**.
