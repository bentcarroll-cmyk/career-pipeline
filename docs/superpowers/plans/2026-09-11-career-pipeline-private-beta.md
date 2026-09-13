# Career Pipeline Private Beta Implementation Plan

> Historical development record: findings, checklists, access settings, and counts describe the stage reviewed here. Consult the [current design notes](../../design.md) and current tests for the present scope and validation limits.

> **For Codex:** Use `superpowers:executing-plans` to implement this plan task by task. Use `superpowers:test-driven-development` for every behavior change and `superpowers:verification-before-completion` before claiming a milestone or release is complete.

**Goal:** Refactor and complete the Career Pipeline Codex Desktop plugin so each user's local folder workspace is the sole system of record, every connector is optional, application packets are created immediately on explicit request, and the private-beta package contains only reusable code, instructions, and synthetic fixtures.

**Architecture:** Canonical opportunity state lives in one immutable-identity folder per qualifying role under `Jobs/JOB-000123/`. Atomic JSON snapshots and append-only events record current state and history. `Indexes/` contains disposable views rebuilt from canonical folders. Deterministic Python helpers enforce locks, allocation, validation, migration, packet versioning, and privacy boundaries; Codex skills handle conversational judgment and connector use. Linear is isolated behind an explicit export boundary and never participates in readiness, identity, deduplication, workflow state, or local delivery.

**Tech stack:** Codex plugin manifest and skills, Python 3.11+ standard library, JSON Schema documents, `unittest`, deterministic ZIP packaging, SHA-256 receipts.

**Approved design:** `docs/superpowers/specs/2026-09-11-career-pipeline-design.md`

## Global constraints

- Never place personal information, real resume text, application material, credentials, private URLs, telemetry, or developer-specific absolute paths in the repository.
- Use fictional employers, people, requisitions, postings, messages, calendar events, and documents in all tests and examples.
- Persist user data only beneath the root approved during onboarding. Persist relative artifact paths inside workspace records.
- Keep final employer-facing PDFs directly under `<approved-root>/Applications/<job>_<company>_<role>/vNNN/`; keep drafts and review evidence in that version's `working/` directory.
- Create packets only after a current, explicit user request. Begin in the same conversation. Never create a packet automation or treat a file, label, or status change as a wake-up event.
- Treat every connector, including Linear, as an independent optional decision. A usable public discovery lane is sufficient for activation.
- Treat `Jobs/` as canonical and `Indexes/` as regenerable. Never delete or rename a canonical job folder to represent lifecycle state.
- Allocate stable six-digit local IDs under a workspace lock and never reuse an allocated number.
- Keep optional export failures outside local transactions. A verified local record remains valid if every export fails.
- Use `apply_patch` for repository edits and commit each completed task as a reviewable checkpoint.

## Existing implementation to preserve or adapt

The prototype already contains a valid plugin shell, privacy scanner, source normalization, evaluation and deduplication helpers, packet versioning and quality receipts, plus synthetic tests. Preserve those behaviors where compatible.

Linear authority remains embedded in:

- `src/career_pipeline/onboarding.py`
- `src/career_pipeline/readiness.py`
- `src/career_pipeline/schema.py`
- `src/career_pipeline/automation_policy.py`
- `src/career_pipeline/linear_delivery.py`
- discovery, backlog, onboarding, packet, and lifecycle skill instructions
- configuration, discovery-state, and delivery schemas
- several existing tests and scripts

There is also uncommitted lifecycle and migration work from the interrupted prototype. Keep it visible, rewrite it against local canonical state, and do not discard it.

## Task 1: Freeze the local workspace contract

**Files:**

- Modify: `src/career_pipeline/contracts.py`
- Modify: `src/career_pipeline/workspace.py`
- Modify: `src/career_pipeline/schema.py`
- Modify: `schemas/config.schema.json`
- Create: `schemas/job.schema.json`
- Create: `schemas/job-event.schema.json`
- Create: `schemas/next-job-id.schema.json`
- Modify: `tests/unit/test_workspace.py`
- Modify: `tests/unit/test_schema.py`
- Create: `tests/unit/test_job_contract.py`
- Modify: `scripts/init_workspace.py`
- Modify: `scripts/validate_workspace.py`

### Step 1: Write failing contract tests

Assert that a new workspace creates:

- `Profile/`, `Sources/`, `Jobs/`, `Applications/`, `Indexes/`, `Runs/discovery/`, `Runs/lifecycle/`, and `State/`;
- `State/next-job-id.json` initialized without reusing an existing allocation;
- a `WorkspacePaths` value exposing `jobs`, `applications`, `indexes`, and `state`; and
- no files or directories inside the plugin repository when the approved root is external.

Assert that configuration validation:

- requires relative paths for `profile`, `sources`, `jobs`, `applications`, `indexes`, `runs`, and `state`;
- accepts a missing or declined Linear connector;
- rejects traversal and absolute persisted subpaths; and
- rejects an unsupported schema version.

Define a minimal valid `job.json` contract with stable local ID, normalized opportunity fields, disposition, lifecycle status, verification time, relative paths, and optional export receipts.

Run:

```bash
python3 -m unittest tests.unit.test_workspace tests.unit.test_schema tests.unit.test_job_contract -v
```

Expected: FAIL because the prototype lacks `Jobs`, `Indexes`, local ID state, and the local job schema.

### Step 2: Implement the workspace and schemas

Extend `WorkspacePaths` and workspace creation without embedding a user-specific location. Initialize new state atomically and leave existing state untouched. Make Linear a normal connector entry rather than a top-level required destination. Keep schemas strict enough to reject malformed state while allowing connector-specific settings only when configured.

### Step 3: Verify and commit

Run the focused tests, plugin validation, and privacy scan.

```bash
python3 -m unittest tests.unit.test_workspace tests.unit.test_schema tests.unit.test_job_contract -v
python3 scripts/validate_plugin.py .
python3 scripts/scan_private_data.py .
git add src/career_pipeline/contracts.py src/career_pipeline/workspace.py src/career_pipeline/schema.py schemas scripts/init_workspace.py scripts/validate_workspace.py tests/unit/test_workspace.py tests/unit/test_schema.py tests/unit/test_job_contract.py
git commit -m "feat: define local workspace contract"
```

## Task 2: Build the canonical job store and lock

**Files:**

- Modify: `src/career_pipeline/atomic.py`
- Create: `src/career_pipeline/job_store.py`
- Create: `tests/unit/test_job_store.py`
- Create: `tests/integration/test_job_store_recovery.py`
- Create: `scripts/create_job.py`
- Create: `scripts/update_job_status.py`

### Step 1: Write failing job-store tests

Cover:

- lock acquisition and release;
- rejection of concurrent mutation while the lock is held;
- allocation of `JOB-000001`, then `JOB-000002`;
- non-reuse after a failed or abandoned allocation;
- a complete canonical folder containing `job.json`, `posting.md`, `assessment.md`, `events.jsonl`, and `working/`;
- temporary-folder cleanup after interrupted creation;
- readback validation before success;
- status changes that atomically rewrite `job.json` and append exactly one event;
- idempotent repeated status updates;
- rejection of invalid statuses and paths; and
- preservation of canonical folders for `not_pursuing` and `closed` records.

Run:

```bash
python3 -m unittest tests.unit.test_job_store tests.integration.test_job_store_recovery -v
```

Expected: FAIL because `job_store.py` does not exist.

### Step 2: Implement mutation primitives

Add a short-lived exclusive lock under `State/`. Use atomic state replacement, a same-filesystem temporary job directory, fsync, rename, and canonical readback. Increment `next-job-id.json` before creating the folder so IDs cannot be reused after failure. Store only relative paths in job records and validate resolved paths remain under the workspace.

Append compact JSON Lines events with event type, timestamp, prior status, resulting status, and synthetic-safe metadata. Do not copy posting bodies or private evidence into events.

### Step 3: Verify and commit

```bash
python3 -m unittest tests.unit.test_job_store tests.integration.test_job_store_recovery -v
python3 scripts/scan_private_data.py .
git add src/career_pipeline/atomic.py src/career_pipeline/job_store.py scripts/create_job.py scripts/update_job_status.py tests/unit/test_job_store.py tests/integration/test_job_store_recovery.py
git commit -m "feat: add canonical local job store"
```

## Task 3: Add disposable local indexes

**Files:**

- Create: `src/career_pipeline/indexes.py`
- Create: `schemas/backlog-index.schema.json`
- Create: `schemas/deduplication-index.schema.json`
- Create: `tests/unit/test_indexes.py`
- Create: `tests/integration/test_index_regeneration.py`
- Create: `scripts/rebuild_indexes.py`

### Step 1: Write failing index tests

Build synthetic canonical folders and assert:

- `backlog.json` includes all canonical records in a stable ordering with summary fields only;
- `deduplication.json` includes requisition and conservative fallback identities;
- closed, not-pursuing, and legacy records still block accidental duplicate creation;
- missing indexes regenerate;
- invalid JSON, invalid schema, stale job hashes, and unknown job IDs trigger a complete rebuild;
- rebuild does not modify any canonical folder bytes; and
- atomic replacement never exposes a partial index.

Run:

```bash
python3 -m unittest tests.unit.test_indexes tests.integration.test_index_regeneration -v
```

Expected: FAIL because the index module does not exist.

### Step 2: Implement regeneration and lookup

Scan `Jobs/JOB-[0-9]{6}/job.json`, validate each snapshot, derive both indexes, and atomically replace them. Include a deterministic source hash or per-record hash so staleness is detectable. Make read helpers repair indexes rather than treating index contents as authority.

### Step 3: Verify and commit

```bash
python3 -m unittest tests.unit.test_indexes tests.integration.test_index_regeneration tests.unit.test_dedupe -v
python3 scripts/scan_private_data.py .
git add src/career_pipeline/indexes.py schemas/backlog-index.schema.json schemas/deduplication-index.schema.json scripts/rebuild_indexes.py tests/unit/test_indexes.py tests/integration/test_index_regeneration.py
git commit -m "feat: add regenerable job indexes"
```

## Task 4: Make onboarding and activation connector-optional

**Files:**

- Modify: `src/career_pipeline/capabilities.py`
- Modify: `src/career_pipeline/onboarding.py`
- Modify: `src/career_pipeline/readiness.py`
- Modify: `src/career_pipeline/automation_policy.py`
- Modify: `schemas/onboarding-state.schema.json`
- Modify: `scripts/check_readiness.py`
- Modify: `scripts/render_automation_prompt.py`
- Modify: `tests/unit/test_onboarding.py`
- Modify: `tests/unit/test_readiness.py`
- Modify: `tests/unit/test_automation_policy.py`
- Modify: `tests/integration/test_onboarding_scenarios.py`
- Modify: `tests/integration/test_activation.py`

### Step 1: Replace prototype expectations with failing local-first tests

Assert:

- onboarding presents one `connectors` stage rather than a required Linear stage;
- Linear may be connected, declined, or unavailable like any other connector;
- every connector decision and observed capability survives resumption;
- activation succeeds with every connector declined when a public discovery lane is usable;
- activation fails for unapproved profile/criteria, incomplete local workspace, invalid timezone, invalid packet defaults, or no discovery lane;
- readiness verifies a safe lock round-trip, canonical job-store read/write test, and index regeneration;
- discovery automation refers to canonical local storage and not Linear;
- lifecycle automation writes derived status locally; and
- `prepare_application` remains forbidden as an automation kind.

Run:

```bash
python3 -m unittest tests.unit.test_onboarding tests.unit.test_readiness tests.unit.test_automation_policy tests.integration.test_onboarding_scenarios tests.integration.test_activation -v
```

Expected: FAIL on the old Linear gate and prompts.

### Step 2: Implement optional connector readiness

Remove `linear_required` and `linear_destination_missing`. Rename connector group constants so they do not imply Linear authority. Require a recorded decision for every connector offered in the current plugin version, while allowing a newly added connector to be introduced through a resumable onboarding/update step. Check actual discovery capabilities rather than installation labels.

### Step 3: Verify and commit

```bash
python3 -m unittest tests.unit.test_onboarding tests.unit.test_readiness tests.unit.test_automation_policy tests.integration.test_onboarding_scenarios tests.integration.test_activation -v
python3 scripts/validate_plugin.py .
python3 scripts/scan_private_data.py .
git add src/career_pipeline/capabilities.py src/career_pipeline/onboarding.py src/career_pipeline/readiness.py src/career_pipeline/automation_policy.py schemas/onboarding-state.schema.json scripts/check_readiness.py scripts/render_automation_prompt.py tests/unit/test_onboarding.py tests/unit/test_readiness.py tests/unit/test_automation_policy.py tests/integration/test_onboarding_scenarios.py tests/integration/test_activation.py
git commit -m "feat: make every connector optional"
```

## Task 5: Deliver discovery and backlog to local canonical state

**Files:**

- Modify: `src/career_pipeline/checkpoints.py`
- Modify: `src/career_pipeline/dedupe.py`
- Create: `src/career_pipeline/discovery.py`
- Modify: `src/career_pipeline/backlog.py`
- Modify: `src/career_pipeline/reporting.py`
- Modify: `schemas/discovery-state.schema.json`
- Modify: `scripts/plan_discovery.py`
- Remove after replacement: `scripts/build_linear_issue.py`
- Remove after replacement: `scripts/record_linear_delivery.py`
- Modify: `tests/integration/test_discovery_delivery.py`
- Modify: `tests/integration/test_cross_source_discovery.py`
- Modify: `tests/integration/test_review_backlog.py`
- Create: `tests/e2e/test_local_discovery.py`

### Step 1: Write failing local-delivery tests

Use Greenhouse, Lever, Ashby, and generic synthetic fixtures. Assert that discovery:

- rebuilds its duplicate baseline from canonical folders;
- filters clear non-matches into run evidence without allocating IDs;
- creates all qualifying novel roles locally;
- repeats duplicate lookup while holding the workspace lock;
- reads each new canonical record back before reporting success;
- commits successful source checkpoints independently;
- does not advance failed source state;
- records a stable batch of local job IDs;
- remains quiet on unchanged results and repeated failures; and
- supports backlog compare, deadline surfacing, and not-pursuing updates without any connector.

Run:

```bash
python3 -m unittest tests.integration.test_discovery_delivery tests.integration.test_cross_source_discovery tests.integration.test_review_backlog tests.e2e.test_local_discovery -v
```

Expected: FAIL because discovery still models Linear delivery.

### Step 2: Implement local discovery orchestration

Compose existing source, evaluation, dedupe, checkpoint, job-store, and index helpers. Keep judgment inputs explicit and deterministic persistence mechanical. Write run evidence before checkpoint completion. Replace `deliveries` with canonical local job mappings or the stable review batch; do not retain an external issue identity in discovery state.

### Step 3: Verify and commit

```bash
python3 -m unittest tests.unit.sources tests.unit.test_evaluation tests.unit.test_dedupe tests.unit.test_checkpoints tests.integration.test_discovery_delivery tests.integration.test_cross_source_discovery tests.integration.test_review_backlog tests.e2e.test_local_discovery -v
python3 scripts/scan_private_data.py .
git add src/career_pipeline/checkpoints.py src/career_pipeline/dedupe.py src/career_pipeline/discovery.py src/career_pipeline/backlog.py src/career_pipeline/reporting.py schemas/discovery-state.schema.json scripts tests/integration/test_discovery_delivery.py tests/integration/test_cross_source_discovery.py tests/integration/test_review_backlog.py tests/e2e/test_local_discovery.py
git commit -m "feat: deliver discovery to local job folders"
```

## Task 6: Bind immediate packets to canonical local jobs

**Files:**

- Modify: `src/career_pipeline/packets.py`
- Modify: `src/career_pipeline/backlog.py`
- Modify: `schemas/application-manifest.schema.json`
- Modify: `scripts/start_packet.py`
- Modify: `scripts/update_packet.py`
- Modify: `scripts/verify_packet_files.py`
- Modify: `tests/unit/test_packets.py`
- Modify: `tests/integration/test_prepare_application.py`
- Modify: `tests/integration/test_packet_resumption.py`
- Modify: `tests/e2e/test_immediate_packets.py`

### Step 1: Write failing local packet tests

Assert:

- selections require exact existing local `JOB-000123` records and a current explicit request;
- the first mutation sets canonical status to `prepare_application` and appends an event only from a pre-application state, without rewinding a later or terminal lifecycle status;
- version allocation is local, monotonic, and resumable;
- manifest paths are workspace-relative rather than absolute;
- final PDFs remain directly browseable in the application version folder;
- no upload or connector receipt is required for `packet_ready`;
- final hashes and paths are read back into the manifest and canonical `job.json`;
- a failed optional export cannot block `packet_ready`;
- repeated or interrupted stages do not duplicate versions, events, or artifacts; and
- multi-job requests preserve user order and role-specific instructions.

Run:

```bash
python3 -m unittest tests.unit.test_packets tests.integration.test_prepare_application tests.integration.test_packet_resumption tests.e2e.test_immediate_packets -v
```

Expected: FAIL because prototype packet stages require upload and Linear delivery verification.

### Step 2: Implement local delivery stages

Use stages `selected`, `posting_verified`, `drafted`, `quality_checked`, `saved`, `local_verified`, and `ready`. Resolve manifest paths through the approved workspace root. After local artifact verification, update the canonical job snapshot and events under the workspace lock, then mark the manifest ready. Preserve every delivered version and any lifecycle status later than packet preparation.

### Step 3: Verify and commit

```bash
python3 -m unittest tests.unit.test_packets tests.unit.test_quality tests.integration.test_prepare_application tests.integration.test_packet_resumption tests.e2e.test_immediate_packets -v
python3 scripts/scan_private_data.py .
git add src/career_pipeline/packets.py src/career_pipeline/backlog.py schemas/application-manifest.schema.json scripts/start_packet.py scripts/update_packet.py scripts/verify_packet_files.py tests/unit/test_packets.py tests/integration/test_prepare_application.py tests/integration/test_packet_resumption.py tests/e2e/test_immediate_packets.py
git commit -m "feat: deliver packets through local canonical state"
```

## Task 7: Reconcile lifecycle evidence into local status

**Files:**

- Modify: `src/career_pipeline/reconciliation.py`
- Modify: `schemas/lifecycle-receipt.schema.json`
- Modify: `scripts/record_lifecycle_evidence.py`
- Modify: `tests/unit/test_reconciliation.py`
- Modify: `tests/integration/test_lifecycle_automation.py`

### Step 1: Adapt the uncommitted tests first

Cover clear application confirmation, rejection, interview, and offer evidence tied to an exact local job. Cover ambiguous employer-only evidence, contradictions, duplicates by opaque source hash, missing canonical jobs, invalid status transitions, and permission limits. Assert full message/calendar bodies are never persisted.

Run:

```bash
python3 -m unittest tests.unit.test_reconciliation tests.integration.test_lifecycle_automation -v
```

Expected: FAIL until the existing work writes canonical local status instead of describing a Linear update.

### Step 2: Implement local reconciliation

Retain the existing classifier where correct. Resolve the exact canonical job, append a minimal receipt under `Runs/lifecycle/`, and perform the local status mutation under the workspace lock. Route ambiguity and contradiction to user review without mutating status.

### Step 3: Verify and commit

```bash
python3 -m unittest tests.unit.test_reconciliation tests.integration.test_lifecycle_automation -v
python3 scripts/scan_private_data.py .
git add src/career_pipeline/reconciliation.py schemas/lifecycle-receipt.schema.json scripts/record_lifecycle_evidence.py tests/unit/test_reconciliation.py tests/integration/test_lifecycle_automation.py
git commit -m "feat: reconcile lifecycle into local job state"
```

## Task 8: Isolate optional exports from canonical workflows

**Files:**

- Create: `src/career_pipeline/exports.py`
- Rename or replace: `src/career_pipeline/linear_delivery.py`
- Replace: `schemas/linear-delivery-receipt.schema.json`
- Create: `schemas/export-receipt.schema.json`
- Create: `scripts/build_export.py`
- Create: `scripts/record_export_receipt.py`
- Modify: `tests/unit/test_linear_delivery.py`
- Modify: `tests/integration/test_discovery_delivery.py`
- Create: `tests/integration/test_optional_exports.py`

### Step 1: Write failing export-boundary tests

Assert that:

- export cannot run without an explicit current user request;
- export reads an existing canonical job or verified packet and never creates a local identity;
- a Linear payload may reference the local job ID but cannot become its status authority;
- successful readback appends a compact optional receipt to the canonical record;
- export errors leave canonical status, packet readiness, indexes, and checkpoints unchanged;
- retry is idempotent using destination plus exported content hash; and
- declining or lacking Linear has no effect on any core test.

Run:

```bash
python3 -m unittest tests.unit.test_linear_delivery tests.integration.test_optional_exports -v
```

Expected: FAIL because the current module treats Linear issue creation as discovery delivery.

### Step 2: Implement the export adapter

Keep destination-specific payload shaping separate from local persistence. Require caller-supplied proof of explicit request. Store only destination kind, opaque destination ID, timestamp, content hash, artifact hashes where applicable, and verified outcome. Never store credentials or complete private drafts.

### Step 3: Verify and commit

```bash
python3 -m unittest tests.unit.test_linear_delivery tests.integration.test_optional_exports tests.integration.test_discovery_delivery -v
python3 scripts/scan_private_data.py .
git add src/career_pipeline/exports.py src/career_pipeline/linear_delivery.py schemas/linear-delivery-receipt.schema.json schemas/export-receipt.schema.json scripts/build_export.py scripts/record_export_receipt.py tests/unit/test_linear_delivery.py tests/integration/test_optional_exports.py tests/integration/test_discovery_delivery.py
git commit -m "feat: isolate optional connector exports"
```

## Task 9: Rewrite plugin instructions around local authority

**Files:**

- Modify: `skills/onboard/SKILL.md`
- Modify: `skills/onboard/references/*.md`
- Modify: `skills/onboard/assets/*automation-prompt.md`
- Modify: `skills/discover-jobs/SKILL.md`
- Modify: `skills/discover-jobs/references/*.md`
- Remove: `skills/discover-jobs/assets/Linear_Issue.template.md`
- Modify: `skills/review-backlog/SKILL.md`
- Modify: `skills/review-backlog/references/backlog-actions.md`
- Modify: `skills/prepare-application/SKILL.md`
- Modify: `skills/prepare-application/agents/openai.yaml`
- Replace: `skills/prepare-application/references/linear-delivery.md`
- Create: `skills/prepare-application/references/local-delivery-and-optional-export.md`
- Modify: `tests/unit/test_plugin_manifest.py`

### Step 1: Write failing instruction assertions

Assert every skill states its authority and safety boundary accurately. Search for forbidden operational claims such as required Linear setup, Linear backlog authority, automatic attachment delivery, and lifecycle writes to Linear. Preserve legitimate references that describe an optional user-requested export.

Run:

```bash
python3 -m unittest tests.unit.test_plugin_manifest -v
rg -n "Linear is required|required Linear|configured Linear destination|Linear backlog|update the exact Linear|deliver.*to Linear" skills src scripts schemas tests
```

Expected: tests or the content audit fail until all core-flow wording is local-first.

### Step 2: Rewrite the skill flows

Onboarding must offer connectors one at a time and activate with public sources. Discovery must create canonical job folders and rebuild indexes. Review must read local canonical records. Prepare application must start immediately from exact local IDs and complete after verified local delivery. Lifecycle must write clear derived status locally. Optional export must always be introduced as an explicit separate action after local success.

### Step 3: Verify and commit

```bash
python3 -m unittest tests.unit.test_plugin_manifest -v
python3 scripts/validate_plugin.py .
python3 scripts/scan_private_data.py .
git add skills tests/unit/test_plugin_manifest.py
git commit -m "docs: align plugin skills with local authority"
```

## Task 10: Add backed-up prototype migration

**Files:**

- Create: `src/career_pipeline/migrations.py`
- Create or modify: `tests/unit/test_migrations.py`
- Create or modify: `tests/integration/test_plugin_update.py`
- Create: `scripts/migrate_workspace.py`
- Create: `docs/private-beta-upgrades.md`

### Step 1: Complete the existing failing migration tests

Assert dry-run by default, explicit confirmation token, backup before write, rollback after simulated interruption, rejection of future schema versions, and byte-for-byte preservation of source resumes and application history. Add coverage for creating missing `Jobs/` and `Indexes/`, converting configuration away from required Linear, and rebuilding indexes without contacting Linear.

Do not silently import or delete Linear issues. If a beta user wants existing issues copied locally, document a separate explicit import decision rather than inferring consent.

Run:

```bash
python3 -m unittest tests.unit.test_migrations tests.integration.test_plugin_update -v
```

Expected: FAIL because `migrations.py` is not yet implemented.

### Step 2: Implement safe migration

Build a deterministic migration plan, show affected paths, require the plan's token, copy mutable state to a timestamped local backup, apply changes atomically, validate, rebuild indexes, and restore original bytes on any error. Never modify `Sources/Resume_Original.*`, `Applications/`, or canonical job history in place.

### Step 3: Verify and commit

```bash
python3 -m unittest tests.unit.test_migrations tests.integration.test_plugin_update -v
python3 scripts/scan_private_data.py .
git add src/career_pipeline/migrations.py scripts/migrate_workspace.py docs/private-beta-upgrades.md tests/unit/test_migrations.py tests/integration/test_plugin_update.py
git commit -m "feat: migrate prototype workspaces safely"
```

## Task 11: Run the synthetic beta gate and package privately

**Files:**

- Create: `tests/e2e/test_private_beta.py`
- Modify: `tests/fixtures/synthetic/**`
- Create: `scripts/package_plugin.py`
- Create: `docs/private-beta-installation.md`
- Create: `CHANGELOG.md`
- Modify: `.gitignore`

### Step 1: Write the end-to-end acceptance test

Run one fictional user through:

- fresh and resumed onboarding with every connector declined;
- activation using public ATS lanes;
- cross-source deduplication and local ID allocation;
- canonical backlog review and not-pursuing status;
- immediate single- and multi-role packets;
- interrupted packet resumption;
- clear and ambiguous lifecycle evidence;
- optional Linear export success and failure; and
- a backed-up update.

Assert final PDFs are directly under synthetic `Applications/` version folders, indexes can be deleted and rebuilt, no scheduler receives packet work, and no connector controls local validity.

Run:

```bash
python3 -m unittest tests.e2e.test_private_beta -v
```

Expected: FAIL until the full local-first composition is complete.

### Step 2: Implement deterministic packaging and beta docs

Package only runtime plugin files and approved documentation. Exclude `.git/`, tests, caches, local environments, generated workspaces, application documents, credentials, and `dist/`. Normalize archive order and timestamps and emit SHA-256. Document private installation, local data ownership, connector choices, immediate packet requests, Applications folder locations, no auto-apply behavior, no telemetry, and safe upgrades.

### Step 3: Run the complete release gate

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_plugin.py .
python3 scripts/scan_private_data.py .
python3 scripts/package_plugin.py --output dist
python3 scripts/validate_plugin.py dist/career-pipeline-plugin.zip
python3 scripts/scan_private_data.py dist/career-pipeline-plugin.zip
git status --short
```

Inspect the archive member list and confirm it contains no generated user workspace or test material.

### Step 4: Commit the beta candidate

```bash
git add .gitignore CHANGELOG.md docs/private-beta-installation.md scripts/package_plugin.py tests/e2e/test_private_beta.py tests/fixtures/synthetic
git commit -m "chore: prepare local-first private beta"
```

## Final acceptance checklist

- [ ] The plugin repository and package contain no personal data, credentials, telemetry, generated application materials, or hardcoded developer paths.
- [ ] Every test and example uses synthetic identities and content.
- [ ] The local folder workspace is the sole system of record.
- [ ] Every qualifying job has one stable canonical `JOB-000123` folder and append-only event history.
- [ ] IDs are never reused, including after interrupted allocation.
- [ ] Missing, corrupt, or stale indexes regenerate without changing canonical job bytes.
- [ ] Every connector can be declined; activation works with a usable public source.
- [ ] Linear appears only as an explicit optional export destination.
- [ ] Discovery creates and reads back local records; clear non-matches remain run evidence.
- [ ] Backlog review reads canonical local state and records local decisions.
- [ ] Explicit application-packet requests begin immediately and are never scheduled.
- [ ] Verified final PDFs are directly browseable under the local `Applications/` folder.
- [ ] Local packet readiness does not depend on an upload or connector.
- [ ] Lifecycle reconciliation writes only unambiguous derived status and minimal receipts locally.
- [ ] Export failures cannot roll back, invalidate, or block canonical local state.
- [ ] Upgrades back up mutable state and preserve resumes, canonical jobs, events, and every application version.
- [ ] The complete test suite, plugin validator, repository privacy scan, archive validator, and archive privacy scan pass from a clean checkout.
