# Career Pipeline Review Remediation Plan

**Source:** `docs/reviews/2026-09-11-tool-review.md`

**Goal:** Resolve every confirmed defect and product improvement from the review in 17 reviewable tasks. The review contains 12 defects and six improvements; Tasks 17 combines the closely related validation and acceptance-test improvements, preserving full scope while yielding 17 implementation tasks.

**Authority:** `docs/superpowers/specs/2026-09-11-career-pipeline-design.md`

## Global constraints

- The user-owned local workspace remains the sole system of record.
- Never delete, overwrite, or silently discard canonical user state, migration evidence, source resumes, job history, or delivered application versions.
- Preserve later user and lifecycle decisions when background or recovery work replays.
- Validate evidence against the approved profile and criteria before it becomes canonical.
- Keep connector use optional and capability based. Export or enrichment capabilities never count as discovery capabilities.
- Keep application creation explicitly user triggered. Never schedule packets or submit applications.
- Store no credentials, telemetry, personal data, or developer-specific paths in the plugin.
- Use synthetic fixtures and temporary workspaces in tests.
- Follow test-first development: demonstrate each regression failing before implementation and passing after it.
- Keep existing public interfaces compatible where practical; document intentional contract changes.

## Task 1: Make migration backups transaction safe

Fix F01 in `src/career_pipeline/migrations.py`.

- Create backups in a staging directory outside the final backup path.
- Verify the copied file inventory and SHA-256 hashes before atomically publishing a completion-marked backup.
- Revalidate the migration plan under the workspace lock before mutating state.
- Never call restore against a backup unless it is complete and verified.
- Ensure failure during any backup copy leaves every original state file byte-for-byte unchanged.
- Add fault-injection tests to `tests/unit/test_migrations.py` for first, middle, and final copy failures and stale-plan application.

## Task 2: Validate journals before persistence

Fix F02 in `src/career_pipeline/job_store.py`.

- Validate the complete pending mutation payload before writing `pending-mutation.json`.
- Rejected input must leave no pending journal and must not block later workspace operations.
- Keep recovery fail closed for a journal that is already corrupt; return a diagnostic containing the affected job ID without exposing user content.
- Add regressions to `tests/integration/test_job_store_recovery.py`.

## Task 3: Make lifecycle reconciliation concurrency safe

Fix F03 in `src/career_pipeline/reconciliation.py` and the minimal supporting job-store API.

- Recheck allowed transitions against the canonical status at commit time.
- Prevent stale evidence from overwriting a newer or terminal user decision.
- Make the persisted receipt and returned decision describe the actual committed result.
- Coordinate receipt deduplication so concurrent runs do not duplicate or contradict receipts.
- Add a deterministic interleaving regression to `tests/integration/test_lifecycle_automation.py`.

## Task 4: Bind packet resumes to approved inputs

Fix F04 in `src/career_pipeline/packets.py` and `scripts/start_packet.py`.

- Load workspace packet defaults rather than assuming cover-letter defaults in the CLI.
- Bind each packet version to the approved profile hash, criteria hash, writing-preferences hash, options, and per-role instructions needed to reproduce it.
- Compare those inputs before resuming an incomplete packet.
- Provide an explicit restart operation that preserves the interrupted version and allocates a new version.
- Add integration coverage in `tests/integration/test_packet_resumption.py` and `tests/integration/test_prepare_application.py`.

## Task 5: Make packet delivery replay consistent

Fix F05 in `src/career_pipeline/packets.py` and `src/career_pipeline/job_store.py`.

- Reconcile an existing canonical application version before changing lifecycle status.
- A replay after interruption must converge the manifest, application history, canonical status, and event history.
- Preserve statuses later than packet preparation, including explicit not-pursuing and terminal states.
- Add failure injection after every delivery persistence boundary in `tests/integration/test_packet_resumption.py`.

## Task 6: Verify delivered packet identity and PDF structure

Fix F06 in `src/career_pipeline/packets.py`, `scripts/verify_packet_files.py`, and packet tests.

- Separate initial artifact hash collection from saved or ready artifact verification.
- Compare current artifact identities and hashes with the recorded saved and delivered receipt.
- Fail for missing, modified, unexpected, or structurally invalid final PDFs.
- Generate minimal real PDFs for successful test fixtures using a test-only helper; do not accept a prefix-only pseudo-PDF.
- Bind quality receipts to the exact approved inputs, drafts, posting snapshot, and final PDF hashes reviewed.

## Task 7: Use one identity-resolution policy

Fix F07 across `src/career_pipeline/dedupe.py`, `src/career_pipeline/indexes.py`, `src/career_pipeline/job_store.py`, and `src/career_pipeline/discovery.py`.

- Use one conservative identity resolver for index lookup, locked duplicate checks, creation, and reverification.
- Match an unambiguous fallback when exactly one side lacks a stable requisition identity.
- Enrich the canonical identity without allocating a new job ID.
- Keep roles with different known requisitions distinct even when fallback fields match.
- Test both discovery orders, ambiguous fallback collisions, and distinct known requisitions.

## Task 8: Enforce assessment evidence validation

Fix F08 in `src/career_pipeline/discovery.py`, `src/career_pipeline/evaluation.py`, and `scripts/plan_discovery.py`.

- Load the currently approved profile and hashes at the delivery boundary.
- Validate every qualifying assessment before ID allocation or canonical update.
- Reject missing responsibilities, unsupported evidence IDs, and stale approval bindings with actionable codes.
- Validate the complete batch before any canonical mutations.
- Add API and CLI regression coverage.

## Task 9: Version assessment changes independently

Fix F09 in `src/career_pipeline/job_store.py` and `src/career_pipeline/discovery.py`.

- Treat posting evidence and profile-to-role assessment as separately replaceable evidence.
- Bind assessment state to profile and criteria hashes.
- Update disposition, strengths, gaps, uncertainties, and assessment evidence when criteria change even if posting content does not.
- Represent an existing role becoming a non-match without deleting history or rewinding its application lifecycle.
- Report the reassessment as a meaningful change.

## Task 10: Normalize documented Lever responses

Fix F10 in `src/career_pipeline/sources/lever.py`, its source contract, CLI routing, and fixtures.

- Preserve the main description, named `lists`, and closing content as responsibilities/evidence.
- Map `workplaceType`.
- Accept explicit employer or board context rather than requiring a nonstandard raw employer field.
- Use a namespaced Lever posting identity when a requisition is unavailable.
- Replace enriched fixtures with synthetic provider-shaped records and cover omitted optional fields.

## Task 11: Make readiness prove activation prerequisites

Fix F11 in `src/career_pipeline/readiness.py` and related configuration/state helpers.

- Verify the preserved resume is a regular file whose size and SHA-256 match the persisted source receipt.
- Validate persisted configuration and onboarding state rather than caller-created mappings alone.
- Validate the configured discovery cadence and timezone.
- Require a public source or a connected connector with a semantic discovery/search action; reject export-only and enrichment-only capabilities.
- Return stable, specific remediation codes and add readiness regressions.

## Task 12: Detect secrets in structured runtime files

Fix F12 in `src/career_pipeline/privacy.py`.

- Detect quoted credential keys and common JSON, YAML, TOML, and environment assignments.
- Keep findings value-free.
- Preserve the runtime allowlist and flag unexpected sensitive file types or obvious credential-bearing files in packaged trees.
- Add synthetic scanner and packaged-archive regressions.

## Task 13: Add quick-start onboarding

Improve the first-use path in `skills/onboard/` and deterministic onboarding helpers.

- Offer a quick-start sequence centered on privacy consent, workspace, resume, target work, hard constraints, profile/criteria approval, one usable public discovery lane, and activation.
- Group optional connectors by purpose and let the user explicitly defer undecided connectors.
- Persist deferral distinctly from decline and let readiness accept deferred nonessential connectors.
- Keep the full interview and connector configuration resumable after activation.
- Update templates, guidance, schemas, and scenario tests.

## Task 14: Add an actionable backlog view

Improve `src/career_pipeline/backlog.py`, `skills/review-backlog/`, schemas, and tests.

- Produce a deterministic ranked action view of active roles, approaching deadlines, facts needing confirmation, and interrupted packets.
- Include job ID, fit reason, major gap, source freshness, deadline, and recommended next action without fabricating missing data.
- Make ranking factors explicit and stable, with user lifecycle decisions taking precedence.
- Support human-readable output through a CLI and keep canonical job folders authoritative.

## Task 15: Separate hard filters from preferences

Add structured search criteria alongside `Profile/Search_Criteria.md`.

- Model compensation, location, work authorization, travel, timing, role, and workplace constraints as hard exclusions, preferences, or unknown-tolerant criteria.
- Distinguish unknown evidence from confirmed mismatch.
- Preserve explicit user ownership of every hard exclusion.
- Bind structured criteria to the approved readable document with a hash.
- Apply deterministic hard filters before semantic fit assessment and record filter outcomes.

## Task 16: Preserve auditable rejection evidence

Improve discovery run evidence in `src/career_pipeline/discovery.py`, schemas, and tests.

- Persist compact non-match and hard-filter decisions with identity, disposition/filter result, reason codes, source receipt reference, and assessment/criteria hash.
- Avoid copying full postings or private profile text into run summaries.
- Make the evidence sufficient to explain an overly strict search and reconsider a role.
- Ensure rejected results do not receive canonical job IDs unless explicitly promoted later.

## Task 17: Unify validation and exercise the real journey

Combine the related validation and acceptance improvements.

- Expand runtime validation to all persisted schema documents or introduce shared validated loaders used at every CLI boundary.
- Align runtime validation with JSON Schema requirements, including required config fields and additional-property handling.
- Add a diagnostic CLI that reports specific repair codes without printing private content.
- Add provider-shaped source fixtures, a real-PDF smoke test, and a clean-install synthetic onboarding → discovery → backlog → packet verification acceptance test.
- Document the private-beta smoke procedure and run it against the packaged archive.
- Keep focused interruption and concurrency regressions from Tasks 1–16 in the standard suite.

## Completion gate

- All task-focused tests and the complete suite pass with pristine output.
- Plugin directory and packaged ZIP validation pass.
- Privacy scanning and deterministic packaging pass.
- A final independent review verifies this plan against the complete branch diff.
- Do not push, publish, merge, or install the plugin without a separate explicit request.
