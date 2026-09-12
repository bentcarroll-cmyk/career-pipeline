# Career Pipeline review

Reviewed September 11, 2026, against commit `836ce7b`. This review makes no implementation changes.

The local workspace, stable job IDs, regenerable indexes, versioned packets, and optional exports form a useful foundation. The next development pass should focus on data preservation, enforcing evidence checks, and making interrupted work recover consistently before adding connectors or features.

**Verification:** All 111 existing tests passed with `PYTHONPATH=src python3 -m unittest discover -s tests -v`. Repository and distribution plugin validation passed; the repository privacy scanner reported zero findings; the distribution checksum passed. Every packaged member matched the current repository file. The failures below were reproduced with synthetic data in temporary workspaces. No real job applications, connector writes, or user-data migrations were performed. Full live Codex onboarding and real document generation were not exercised.

The green suite does not establish that the complete product works: current packet end-to-end tests use placeholder PDF bytes and supplied passing quality receipts, and source fixtures contain enrichment absent from provider responses.

**Priority:** P1 means fix before relying on the affected release path; P2 means a concrete correctness defect to fix in the next development pass. The order below is grouped by workflow rather than a strict implementation sequence.

## Confirmed defects

### F01 — P1: An interrupted migration backup can delete original state

**Code:** `src/career_pipeline/migrations.py:202–206`, with deletion at `159–162`.

The backup directory is created before copying completes. If a copy fails, rollback treats the partial directory as a complete backup and deletes original state files that are absent from it.

**Reproduction:** Seed configuration, discovery state, onboarding state, and the next-ID counter. Fail copying discovery state after configuration was copied. After the failed migration, only configuration remains. The error incorrectly says the original state was restored.

**Fix:** Copy to a staging directory, verify a complete inventory and hashes, then publish the backup atomically. Begin migration mutations only after that succeeds. Never restore from an incomplete backup. Also revalidate the planned configuration under the lock before applying it.

**Regression:** Inject failure at each backup-copy boundary and verify that every original file remains byte-for-byte unchanged.

### F02 — P2: Rejected input can block every later workspace mutation

**Code:** `src/career_pipeline/job_store.py:431–442`; recovery validation at `394–400`.

The mutation helper persists its recovery journal before validating all its contents. A changed posting with empty posting evidence creates a journal that recovery immediately rejects. Each subsequent lock acquisition retries that invalid journal and fails, including operations unrelated to the job.

**Reproduction:** Reverify a job with newer changed content and an empty `posting_markdown`. The pending journal remains; a subsequent job-ID allocation fails with the same invalid-mutation error.

**Fix:** Validate the complete proposed journal before writing it. Provide an explicit diagnostic recovery path for already-corrupt journals that preserves evidence and does not silently discard work.

**Regression:** Invalid evidence creates no pending journal and does not prevent a later valid update or allocation.

### F03 — P2: Lifecycle reconciliation can overwrite a newer user decision

**Code:** `src/career_pipeline/reconciliation.py:213–236`.

Matching and transition classification use an unlocked snapshot. The subsequent status update does not constrain the prior status. A user or another run can close a job after classification, then a stale application-confirmation decision changes it back to applied.

**Reproduction:** Insert a valid closed-status update between classification and the automatic update. Reconciliation reports an applied update and leaves the job applied.

**Fix:** Recheck the transition under the mutation lock. Coordinate evidence deduplication, transition, and receipt persistence, and report the actual committed result. Preserve later and terminal statuses.

**Regression:** Interleave classification with a terminal update and verify that the terminal decision survives and the receipt accurately reports the result.

### F04 — P2: Changed profile facts and packet options are ignored on resume

**Code:** `src/career_pipeline/packets.py:215–219`; `scripts/start_packet.py:37–43`.

Any incomplete packet is resumed without comparing the requested profile hash or options. The CLI never supplies a profile hash. Although `resume_action` can identify a changed profile, the start path does not use it, and there is no supported restart operation while an incomplete version exists.

**Reproduction:** Start with an old profile hash and no cover letter. Request the same job with a new profile hash and an enabled cover letter. The result is still the old v001, old profile hash, and no cover letter.

**Fix:** Load the approved profile hash and workspace packet defaults at start. Bind the version to profile, criteria, writing preferences, and role instructions. Compare those inputs before resuming, and support an explicit restart that preserves the interrupted version.

**Regression:** Correct the profile during interrupted work; verify that resumption requires the documented version decision and that a restart allocates a fresh version without overwriting history.

### F05 — P2: Interrupted packet delivery can finish with conflicting statuses

**Code:** `src/career_pipeline/packets.py:195–204,419–441`; `src/career_pipeline/job_store.py:647–655`.

Canonical delivery commits before the manifest reaches ready. If execution stops between those writes, starting again changes the job from packet-ready to prepare-application. Replaying delivery sees the existing application version and returns without repairing the status.

**Reproduction:** Fail the index-load step after recording the application version. Before retry: canonical job is packet-ready and manifest is saved. After documented start-and-complete retry: canonical job is prepare-application and manifest is ready.

**Fix:** Reconcile the existing version before changing status, or make delivery replay restore the eligible canonical status. Preserve any later user or lifecycle decision.

**Regression:** Interrupt after each delivery write and verify consistent manifest, application history, canonical status, and event count after retry.

### F06 — P2: Packet verification accepts modified delivered files

**Code:** `src/career_pipeline/packets.py:373–385,398–399`; `scripts/verify_packet_files.py:24–32`.

The artifact verifier computes hashes but never compares them with the recorded delivery hashes. A ready packet also bypasses verification in `complete_local_delivery`.

**Reproduction:** Replace a delivered resume with different PDF-prefixed bytes. The verifier reports valid even though its calculated hash differs from the saved hash. The verification CLI therefore exits successfully.

**Fix:** Separate initial hash collection from verification of saved or delivered artifacts. Compare exact expected identities and hashes on re-verification. Use an actual PDF parser for structural checks; a `%PDF-` prefix alone does not establish a usable PDF.

**Regression:** Modified, missing, malformed, and unexpected final files fail verification; unchanged real PDFs pass.

### F07 — P2: Mixed requisition availability breaks deduplication

**Code:** `src/career_pipeline/discovery.py:78–92`; `src/career_pipeline/job_store.py:461–475`; `src/career_pipeline/indexes.py:64–75`.

The index supports both requisition and fallback identities, but reverification compares only the preferred identity. A record with a requisition rediscovered without one matches the index and then raises an identity mismatch, aborting the discovery batch. In the reverse order, the same opportunity can receive a second job ID.

**Reproduction:** Deliver identical employer/title/location/team records with and without a requisition, in both orders. One order raises; the other creates JOB-000002.

**Fix:** Share one conservative identity-resolution policy across lookup, locked creation, and reverification. Allow unambiguous enrichment when one side lacks stable identity, while keeping records with different known requisitions distinct.

**Regression:** Test both discovery orders, ambiguous fallback collisions, and two distinct known requisitions with otherwise identical fields.

### F08 — P2: Evidence validation is bypassed when saving jobs

**Code:** `src/career_pipeline/discovery.py:73–103`; `scripts/plan_discovery.py:83–90`; validator in `src/career_pipeline/evaluation.py:27–78`.

The evidence validator rejects missing responsibilities and nonexistent profile evidence IDs, but the delivery path neither calls it nor loads approved profile evidence.

**Reproduction:** A qualifying assessment with no responsibilities and a nonexistent evidence ID produces both validation errors, yet delivery still creates a canonical job containing the unsupported claim.

**Fix:** Require validated assessment input bound to the currently approved profile. Validate before allocating IDs or replacing canonical assessments, and return actionable errors for invalid items. Preserve semantic review in the skill while enforcing deterministic checks in code.

**Regression:** Unsupported strengths, empty responsibilities, and stale approval hashes cannot enter the canonical backlog through either the API or CLI.

### F09 — P2: Updated fit assessments leave obsolete recommendations in place

**Code:** `src/career_pipeline/job_store.py:505–527`; `src/career_pipeline/discovery.py:75–77`.

Assessment replacement is coupled to posting-content or source changes. If approved preferences change while the posting stays the same, a new assessment is ignored. A reassessed non-match is skipped before looking up the existing canonical job.

**Reproduction:** Reassess a strong match first as worth considering, then as a non-match, without changing the posting. Both runs leave the canonical strong-match classification unchanged and report no meaningful changes.

**Fix:** Version posting evidence and fit assessment independently. Bind assessments to profile and criteria hashes. Explicitly represent a saved role becoming a non-match or needing reassessment without deleting its history or changing the user's application status.

**Regression:** Criteria-only changes update fit, strengths, gaps, and assessment evidence, and generate an appropriate change report.

### F10 — P2: Lever normalization omits real posting fields

**Code:** `src/career_pipeline/sources/lever.py:35–47`.

Lever documents additional posting sections in `lists` and the work environment in `workplaceType`. The adapter ignores the former and reads `workplace_model` instead of the latter. Employer and requisition are also assumed to exist in an enriched payload, without explicit board context in the source contract. See the [official Lever API documentation](https://github.com/lever/postings-api#get-a-list-of-job-postings).

**Reproduction:** A provider-shaped synthetic response with a company introduction, a list of actual duties and a mandatory qualification, and a remote workplace normalizes to only the introduction as responsibilities, with no workplace model or employer.

**Fix:** Preserve named posting sections, map documented provider fields, and accept explicit employer/board context and a namespaced ATS posting identity. Check the other adapters against their documented raw response shapes too.

**Regression:** Use synthetic values in fixtures that retain real provider schemas, including omitted optional fields and substantive requirements outside the main description.

### F11 — P2: Readiness can pass without the promised source and resume checks

**Code:** `src/career_pipeline/readiness.py:53–66,111–123`.

Resume checking counts matching paths but never verifies that the match is a file or matches its source receipt. Source readiness accepts any connected connector with any capability, including an export-only connector. Schedule validation and persisted configuration validation are also absent despite being promised in onboarding guidance.

**Reproduction:** Readiness returns no failure codes after the preserved resume is modified, and again after it is replaced with a same-named directory. A configuration whose only enabled discovery source is Linear with create-issue capability also passes.

**Fix:** Verify the source file, size, and hash against its receipt. Define discovery-source capabilities separately from enrichment/export capabilities. Validate the persisted configuration, cadence, and usable source setup before allowing activation.

**Regression:** Changed or non-file resumes, export-only sources, invalid schedules, and malformed persisted state fail with specific remediation codes.

### F12 — P2: The privacy scanner misses quoted JSON credential keys

**Code:** `src/career_pipeline/privacy.py:20–22`.

The credential regex expects the separator immediately after the field name. A closing quote around a JSON key prevents matching. Packaging relies on this scanner, so an accidentally included credential in a runtime JSON file could pass the release gate.

**Reproduction:** A temporary JSON file with quoted credential keys and synthetic values produces zero findings. This demonstrates a detection gap; the review did not find actual credentials in the repository.

**Fix:** Handle quoted keys or inspect supported structured configuration formats. Keep reported findings value-free. Retain the runtime-tree allowlist and add stricter checks for unexpected files within those trees.

**Regression:** Synthetic credentials are detected in JSON, YAML, TOML, and environment assignments, without printing their values.

## Product and maintenance improvements

1. **Shorten the first useful session.** Offer a quick start built around the resume, target work, hard constraints, and profile approval. Group optional connector decisions and permit explicit deferral until the connector is useful. Eleven separate connector discussions before the first search add friction.
2. **Show an actionable backlog.** Provide a small ranked view of roles to review, deadlines, facts needing confirmation, and interrupted packets. Every recommendation should show its fit reason, major gap, source freshness, and next action. This can be a local report or conversational view; a hosted dashboard is unnecessary.
3. **Separate hard filters from preferences.** Store compensation, location, authorization, travel, and timing rules in structured criteria alongside the readable document. Distinguish unknown evidence from a confirmed mismatch. Preserve user control over what counts as a hard exclusion.
4. **Make rejected results auditable.** Discovery run evidence currently retains non-match keys but omits their assessment and reasons. Preserve a compact rejection rationale and source receipt so the user can diagnose an overly strict search and reconsider a role.
5. **Unify configuration and validation.** Thirteen schema documents exist, but the runtime validator handles only config and job, and config validation omits several schema-required fields. Use shared validated loaders at CLI boundaries, load packet defaults centrally, and provide a diagnostic command with specific repair instructions.
6. **Test the actual user journey.** Add a real-PDF smoke test, provider-shaped source fixtures, and a documented clean-install/onboarding/discovery/packet exercise. Keep focused fault-injection tests for each confirmed recovery and concurrency bug. Bind quality receipts to the exact profile, draft, posting, and PDF hashes reviewed.

## Suggested implementation order

1. Fix migration backup safety (F01) and add interruption regressions.
2. Fix invalid journals and concurrent lifecycle writes (F02–F03).
3. Enforce assessment validation, repair identity matching, and separate reassessment from posting changes (F07–F09).
4. Repair packet input binding, restart, delivery replay, and verification (F04–F06).
5. Correct adapter/readiness/privacy checks and add realistic acceptance fixtures (F10–F12).
6. Improve onboarding and backlog presentation once these correctness fixes pass their regressions.
