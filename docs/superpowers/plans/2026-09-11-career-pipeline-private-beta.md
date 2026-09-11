# Career Pipeline Private Beta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a private-beta Codex Desktop plugin that onboards a user into a local-first career workspace, discovers and tracks qualifying roles in Linear, creates verified application packets immediately on explicit request, and optionally reconciles lifecycle evidence.

**Architecture:** The repository is the plugin root. Four concise Codex skills orchestrate connector calls and user conversations, while a dependency-light Python package owns deterministic state transitions, schemas, paths, deduplication, manifests, migrations, and privacy checks. Connector responses and document/PDF operations cross explicit JSON boundaries so the core can be tested with synthetic fixtures and the plugin never needs a developer-operated service.

**Tech Stack:** Codex Desktop plugin manifest and skills (Markdown/YAML/JSON), Python 3.11+ standard library, JSON Schema documents, `unittest`, Codex connector tools, Codex document/PDF capabilities, Git

**Spec:** `docs/superpowers/specs/2026-09-11-career-pipeline-design.md`

## Global Constraints

- The plugin name is exactly `career-pipeline`.
- Version one contains exactly four user-facing skills: Onboard, Discover jobs, Review backlog, and Prepare application.
- Linear is required; every other connector is offered, capability-tested, accepted, or declined independently.
- Declining Linear prevents activation. Declining any optional connector preserves a documented fallback.
- Discovery defaults to twice each weekday in the user's timezone, with daily, weekly, and custom alternatives.
- Application packets are created immediately in the current conversation after an explicit user request; packet creation is never a scheduled automation and a manually added Linear label is never a wake-up event.
- Final employer-facing PDFs are stored directly under `<approved-root>/Applications/<ticket>_<company>_<role>/vNNN/`; private drafts and evidence stay in that version's `working/` folder.
- The source résumé is copied unchanged, hashed, and never overwritten.
- User data lives only in the user-approved local workspace and the user's connected services. The plugin has no hosted service, shared database, telemetry, analytics SDK, remote logging, hidden destination, or developer-controlled credential.
- Repository content, tests, examples, and release artifacts contain only synthetic people, employers, postings, messages, tickets, and documents.
- Reusable files use configuration values, temporary directories, and relative paths; they contain no developer username, personal identifier, private URL, credential, or fixed user filesystem path.
- State writes are atomic. Interrupted onboarding, discovery, packet, and migration workflows resume idempotently.
- Linear issue creation, packet upload, and attachment delivery are read back before state advances.
- Clear non-matches remain in local run evidence and are never created in Linear.
- No workflow submits an application, sends a message, accepts an invitation, creates a calendar event, or contacts another person without a separate explicit request.
- Schema migrations require confirmation, create a backup first, and never overwrite application history.
- Every implementation task uses synthetic fixtures and ends with a focused verification and reviewable commit.

---

## File and responsibility map

### Plugin entrypoints

- `.codex-plugin/plugin.json` — installable plugin metadata; advertises skills only and declares no custom app or MCP server.
- `skills/onboard/SKILL.md` — resumable privacy, workspace, connector, résumé, interview, approval, readiness, and automation-activation conversation.
- `skills/discover-jobs/SKILL.md` — manual or scheduled source search, normalization, verification, assessment, deduplication, Linear delivery, and quiet reporting.
- `skills/review-backlog/SKILL.md` — compare existing Linear opportunities, record dispositions, surface deadlines, and route explicit selections into immediate packet work.
- `skills/prepare-application/SKILL.md` — immediate single- or multi-ticket packet generation, quality gates, local versioning, Linear delivery, and resumption.
- `skills/*/agents/openai.yaml` — UI metadata and invocation policy for each skill.
- `skills/*/references/*.md` — substantial workflow rules loaded only by the relevant skill.
- `skills/*/assets/*` — synthetic, user-data-free profile, ticket, résumé, cover-letter, and automation-prompt templates.

### Deterministic runtime

- `src/career_pipeline/atomic.py` — atomic JSON and text writes.
- `src/career_pipeline/contracts.py` — typed dataclasses and enum-like literals shared across commands.
- `src/career_pipeline/schema.py` — local schema validation and version checks.
- `src/career_pipeline/workspace.py` — safe workspace creation, path resolution, and source résumé preservation.
- `src/career_pipeline/onboarding.py` — resumable onboarding transitions and connector decisions.
- `src/career_pipeline/readiness.py` — activation gates and automation eligibility.
- `src/career_pipeline/automation_policy.py` — allowed automation kinds and prompt rendering; rejects packet automation.
- `src/career_pipeline/sources/*.py` — normalization for Greenhouse, Lever, Ashby, and generic connector snapshots.
- `src/career_pipeline/evaluation.py` — validation of evidence-backed fit assessments.
- `src/career_pipeline/dedupe.py` — requisition identity and conservative fallback fingerprints.
- `src/career_pipeline/checkpoints.py` — independent source-success and stable-batch state.
- `src/career_pipeline/linear_delivery.py` — issue payloads, final duplicate checks, and readback receipts.
- `src/career_pipeline/packets.py` — safe names, version allocation, manifest transitions, hashes, and resume logic.
- `src/career_pipeline/reconciliation.py` — exact-role lifecycle evidence decisions and minimal receipts.
- `src/career_pipeline/migrations.py` — versioned, confirmed, backed-up state migrations.
- `src/career_pipeline/privacy.py` — repository/package scans for sensitive content and forbidden destinations.
- `scripts/*.py` — thin CLI adapters over the package; no business rules live only in a CLI file.
- `schemas/*.schema.json` — committed contracts for configuration, state, normalized jobs, assessments, delivery receipts, packet manifests, and lifecycle receipts.

### Verification and distribution

- `tests/unit/` — focused standard-library tests for every deterministic module.
- `tests/integration/` — fake-source and fake-Linear workflow tests.
- `tests/e2e/` — synthetic onboarding, discovery, immediate packet, resumption, lifecycle, and upgrade scenarios.
- `tests/fixtures/synthetic/` — fictional profiles, postings, connector snapshots, Linear records, and mail/calendar evidence.
- `scripts/validate_plugin.py` — repository-local packaging and manifest preflight.
- `scripts/scan_private_data.py` — fail-closed privacy/credential/path scan.
- `scripts/package_plugin.py` — reproducible archive builder with an explicit inclusion list.
- `README.md` — private-beta installation, start prompt, behavior boundaries, and local workspace locations.
- `PRIVACY.md` — accurate local/connector data handling statement.
- `SECURITY.md` — credential handling and private vulnerability-reporting instructions.
- `docs/BETA_TESTING.md` — three-to-five-user manual acceptance checklist with no telemetry.
- `CHANGELOG.md` — semver release history.

## Milestone map

1. **Plugin shell and onboarding:** Tasks 1–4.
2. **Discovery and backlog:** Tasks 5–7.
3. **Immediate application packets:** Tasks 8–9.
4. **Lifecycle and beta hardening:** Tasks 10–12.

---

### Task 1: Private-safe plugin shell

**Files:**
- Create: `.codex-plugin/plugin.json`
- Create: `pyproject.toml`
- Create: `src/career_pipeline/__init__.py`
- Create: `src/career_pipeline/privacy.py`
- Create: `scripts/scan_private_data.py`
- Create: `scripts/validate_plugin.py`
- Create: `skills/onboard/SKILL.md`
- Create: `skills/discover-jobs/SKILL.md`
- Create: `skills/review-backlog/SKILL.md`
- Create: `skills/prepare-application/SKILL.md`
- Create: `tests/unit/test_plugin_manifest.py`
- Create: `tests/unit/test_privacy.py`
- Modify: `.gitignore`
- Include unchanged: `docs/superpowers/specs/2026-09-11-career-pipeline-design.md`
- Include unchanged: `docs/superpowers/plans/2026-09-11-career-pipeline-private-beta.md`

**Interfaces:**
- Produces: `scan_tree(root: Path) -> list[Finding]`
- Produces: `validate_manifest(root: Path) -> list[str]`
- Produces: installable manifest name `career-pipeline`, version `0.1.0`, and skills path `./skills/`
- Consumes: no earlier runtime interfaces

- [ ] **Step 1: Write manifest and privacy failure tests**

Create tests that parse the manifest, require strict semver and the four expected skill directories, reject `apps` and `mcpServers`, and scan a temporary tree containing constructed secret, personal-path, private-URL, telemetry, and application-document examples.

```python
def test_manifest_exposes_only_skills(self):
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())
    self.assertEqual(manifest["name"], "career-pipeline")
    self.assertEqual(manifest["version"], "0.1.0")
    self.assertEqual(manifest["skills"], "./skills/")
    self.assertNotIn("apps", manifest)
    self.assertNotIn("mcpServers", manifest)

def test_scan_rejects_sensitive_tree(self):
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "unsafe.txt").write_text("api" + "_key=synthetic-secret-value")
        self.assertTrue(scan_tree(root))
```

- [ ] **Step 2: Run the tests and confirm the empty shell fails**

Run: `python3 -m unittest tests.unit.test_plugin_manifest tests.unit.test_privacy -v`  
Expected: FAIL because the manifest and privacy module do not exist.

- [ ] **Step 3: Implement the minimal package, manifest, and valid skill entrypoints**

Create a manifest with a neutral publisher name, no email or personal URL, at most three starter prompts, and no connector endpoint. Give each of the four skill folders valid frontmatter plus a concise, accurate boundary: Onboard requires Linear and explicit activation approval; Discover jobs creates only qualifying backlog issues; Review backlog never submits; Prepare application requires an explicit request and starts immediately without scheduling. Implement `Finding(path, line, rule)`, binary-file skipping, an explicit package allowlist, and rules for credentials, email addresses, user-home paths, private URLs, telemetry SDKs, generated workspace directories, and common application file formats. Make the CLI exit nonzero and print relative paths only when findings exist.

- [ ] **Step 4: Add repository-local manifest validation**

Validate required fields, semver, relative in-archive paths, referenced files, skill frontmatter, absence of scaffold markers, and absence of unsupported manifest fields. Keep the validator dependency-free.

- [ ] **Step 5: Run shell verification**

Run: `python3 -m unittest tests.unit.test_plugin_manifest tests.unit.test_privacy -v`  
Expected: PASS.

Run: `python3 scripts/scan_private_data.py .`  
Expected: PASS with zero findings.

Run: `python3 scripts/validate_plugin.py .`  
Expected: PASS with exactly four valid skill entrypoints.

- [ ] **Step 6: Commit the private-safe shell**

```bash
git add .gitignore .codex-plugin pyproject.toml src scripts tests docs/superpowers
git commit -m "chore: initialize private-safe career pipeline plugin"
```

---

### Task 2: Workspace, schemas, and atomic state

**Files:**
- Create: `schemas/config.schema.json`
- Create: `schemas/onboarding-state.schema.json`
- Create: `schemas/discovery-state.schema.json`
- Create: `schemas/application-manifest.schema.json`
- Create: `src/career_pipeline/atomic.py`
- Create: `src/career_pipeline/contracts.py`
- Create: `src/career_pipeline/schema.py`
- Create: `src/career_pipeline/workspace.py`
- Create: `scripts/init_workspace.py`
- Create: `scripts/validate_workspace.py`
- Create: `tests/unit/test_atomic.py`
- Create: `tests/unit/test_workspace.py`
- Create: `tests/unit/test_schema.py`

**Interfaces:**
- Produces: `atomic_write_json(path: Path, value: Mapping[str, object]) -> None`
- Produces: `load_json(path: Path) -> dict[str, object]`
- Produces: `create_workspace(root: Path) -> WorkspacePaths`
- Produces: `preserve_source_resume(source: Path, paths: WorkspacePaths) -> SourceReceipt`
- Produces: `validate_document(schema_name: str, value: Mapping[str, object]) -> list[ValidationError]`
- `WorkspacePaths` exposes `profile`, `sources`, `applications`, `runs`, and `state` paths derived from the approved root.

- [ ] **Step 1: Write failing atomic and workspace tests**

Use `TemporaryDirectory` exclusively. Assert the exact standard directory tree, fsync-and-replace behavior, recovery from a simulated interrupted temporary write, refusal to overwrite an existing source résumé, and byte-for-byte hash preservation.

```python
def test_resume_is_preserved_without_overwrite(self):
    source = self.temp / "Synthetic_Resume.txt"
    source.write_bytes(b"Synthetic candidate experience\n")
    paths = create_workspace(self.root)
    first = preserve_source_resume(source, paths)
    second = preserve_source_resume(source, paths)
    self.assertEqual(first.sha256, second.sha256)
    self.assertEqual(first.destination.read_bytes(), source.read_bytes())
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python3 -m unittest tests.unit.test_atomic tests.unit.test_workspace tests.unit.test_schema -v`  
Expected: FAIL because the state and workspace interfaces are absent.

- [ ] **Step 3: Implement typed contracts and schemas**

Define schema version `1`; connector decisions `connected | declined | unavailable`; onboarding stages from `privacy` through `active`; per-source checkpoint status; and packet stage values from `selected` through `ready`. Require timezone, Linear destination, approved profile flags, packet defaults, source capabilities, and relative workspace subpaths in `config.json`.

- [ ] **Step 4: Implement safe workspace and state operations**

Reject roots that resolve inside the plugin repository, create only the spec's directories, use `Path.resolve()` plus containment checks, write via a same-directory temporary file followed by `os.replace`, and preserve every existing application version. Record the original résumé's source filename, destination, size, and SHA-256 without persisting its extracted text in config.

- [ ] **Step 5: Run deterministic verification**

Run: `python3 -m unittest tests.unit.test_atomic tests.unit.test_workspace tests.unit.test_schema -v`  
Expected: PASS.

Run: `python3 scripts/init_workspace.py --root "$(mktemp -d)/Synthetic-Career" --dry-run`  
Expected: prints only relative directories and performs no writes.

- [ ] **Step 6: Commit workspace foundations**

```bash
git add schemas src/career_pipeline scripts/init_workspace.py scripts/validate_workspace.py tests/unit
git commit -m "feat: add private workspace and atomic state contracts"
```

---

### Task 3: Resumable onboarding, Linear requirement, and optional connectors

**Files:**
- Create: `src/career_pipeline/onboarding.py`
- Create: `src/career_pipeline/capabilities.py`
- Modify: `skills/onboard/SKILL.md`
- Create: `skills/onboard/agents/openai.yaml`
- Create: `skills/onboard/references/privacy-and-consent.md`
- Create: `skills/onboard/references/connectors.md`
- Create: `skills/onboard/references/interview.md`
- Create: `skills/onboard/assets/Career_Profile.template.md`
- Create: `skills/onboard/assets/Search_Criteria.template.md`
- Create: `skills/onboard/assets/Writing_Preferences.template.md`
- Create: `tests/unit/test_onboarding.py`
- Create: `tests/integration/test_onboarding_scenarios.py`
- Create: `tests/fixtures/synthetic/onboarding/*.json`
- Create: `tests/fixtures/synthetic/resume/Synthetic_Resume.txt`

**Interfaces:**
- Consumes: `WorkspacePaths`, `atomic_write_json`, and schema validation from Task 2.
- Produces: `record_connector_decision(state, connector, decision, capabilities) -> OnboardingState`
- Produces: `advance_onboarding(state, completed_stage, receipt) -> OnboardingState`
- Produces: `record_profile_approval(state, profile_hash, criteria_hash) -> OnboardingState`
- Produces: a capability matrix keyed by `linear`, `indeed`, `linkedin`, `firecrawl`, `browser`, `notion`, `github`, `gmail`, `google-calendar`, `google-drive`, and `usajobs`.

- [ ] **Step 1: Write failing onboarding state tests**

Cover complete onboarding, interruption after every stage, resume from the recorded next stage, Linear unavailable, every optional connector declined independently, a connector installed without its expected action, and a correction that supersedes résumé-derived text.

```python
def test_optional_decline_does_not_block_progress(self):
    state = synthetic_state_at("optional_connectors")
    next_state = record_connector_decision(
        state, "notion", "declined", capabilities=[]
    )
    self.assertEqual(next_state.connectors["notion"].decision, "declined")
    self.assertEqual(next_state.stage, "optional_connectors")

def test_linear_decline_blocks_activation(self):
    state = synthetic_ready_state(linear="declined")
    self.assertIn("linear_required", readiness_failures(state))
```

- [ ] **Step 2: Run onboarding tests and verify failure**

Run: `python3 -m unittest tests.unit.test_onboarding tests.integration.test_onboarding_scenarios -v`  
Expected: FAIL because the state machine and Onboard skill are absent.

- [ ] **Step 3: Implement resumable onboarding state**

Persist a receipt after each completed stage. Make stage transitions monotonic except explicit correction loops. Store connector choice separately from tested actions; an installed connector with missing required actions is `unavailable`, not `connected`. Preserve declines across resumed runs.

- [ ] **Step 4: Write the Onboard skill and progressive references**

The entry skill starts from “Set up my job search,” accurately explains local and third-party processing, requests approval for the root before creating it, and handles connectors one at a time. The Linear section verifies issue search/create/read, labels, views, comments, and attachment actions in the selected existing workspace/team/project. Each optional connector section states benefit, intended access, fallback, connect/skip choice, and observed capabilities without overstating coverage.

- [ ] **Step 5: Add résumé, interview, and explicit approval flow**

Copy the source résumé unchanged, derive a draft evidence inventory, ask the approved interview topics, and write the three profile documents from synthetic-free templates. Require the user to correct and explicitly approve both career profile and search criteria; later corrections replace conflicting résumé-derived assumptions and update approval hashes.

- [ ] **Step 6: Run onboarding verification**

Run: `python3 -m unittest tests.unit.test_onboarding tests.integration.test_onboarding_scenarios -v`  
Expected: PASS for connected, declined, unavailable, interrupted, resumed, corrected, and approval-gated scenarios.

Run: `python3 scripts/scan_private_data.py .`  
Expected: PASS; all fixture identities are declared synthetic and no fixture resembles real application material.

- [ ] **Step 7: Commit onboarding**

```bash
git add src/career_pipeline skills/onboard tests
git commit -m "feat: add resumable private onboarding"
```

---

### Task 4: Readiness and approved automation activation

**Files:**
- Create: `src/career_pipeline/readiness.py`
- Create: `src/career_pipeline/automation_policy.py`
- Create: `skills/onboard/references/readiness-and-activation.md`
- Create: `skills/onboard/assets/discovery-automation-prompt.md`
- Create: `skills/onboard/assets/lifecycle-automation-prompt.md`
- Create: `scripts/check_readiness.py`
- Create: `scripts/render_automation_prompt.py`
- Create: `tests/unit/test_readiness.py`
- Create: `tests/unit/test_automation_policy.py`
- Create: `tests/integration/test_activation.py`

**Interfaces:**
- Consumes: approved hashes, connector decisions, paths, and schedule values from Tasks 2–3.
- Produces: `check_readiness(config, onboarding, capabilities) -> ReadinessReport`
- Produces: `render_automation(kind: Literal["discovery", "lifecycle"], config) -> str`
- Produces: `automation_allowed(kind, readiness) -> bool`; every other kind raises `UnsupportedAutomation`.

- [ ] **Step 1: Write failing readiness and automation tests**

Assert activation fails for missing Linear actions, missing approved profile/criteria, unwritable workspace, invalid timezone, and zero usable discovery sources. Assert discovery defaults to two weekday runs in the user's timezone, lifecycle is offered only with Gmail or Calendar, and any `prepare_application` schedule request is rejected.

```python
def test_packet_automation_is_impossible(self):
    with self.assertRaises(UnsupportedAutomation):
        render_automation("prepare_application", synthetic_ready_config())

def test_activation_requires_explicit_profile_approval(self):
    report = check_readiness(config, onboarding_without_approval(), capabilities)
    self.assertIn("profile_not_approved", report.failure_codes)
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python3 -m unittest tests.unit.test_readiness tests.unit.test_automation_policy tests.integration.test_activation -v`  
Expected: FAIL because readiness and policy modules are absent.

- [ ] **Step 3: Implement readiness with actionable failures**

Return stable failure codes plus user-facing remediation. Verify local files, safe resolved paths, Linear destination/capabilities, at least one discovery lane, connector decisions, timezone, packet defaults, and approval hashes. Do not infer readiness from a résumé alone.

- [ ] **Step 4: Implement automation prompt policy**

Render cohesive user-visible prompts from configuration without embedding personal content. Discovery prompts invoke the Discover jobs skill and stay quiet on unchanged/no-result runs. Lifecycle prompts reconcile only when enabled and stay quiet without a clear change or action. The allowed-kind enum deliberately has no packet member.

- [ ] **Step 5: Update Onboard activation instructions**

After a passing readiness report, show the selected cadence and ask one explicit approval before using the Codex automation tool. Record returned automation identifiers only after readback. Do not create an automation when the user merely approves the profile.

- [ ] **Step 6: Verify Milestone 1**

Run: `python3 -m unittest discover -s tests -p 'test_*.py' -v`  
Expected: all shell and onboarding tests PASS.

Run: `python3 scripts/check_readiness.py --fixture tests/fixtures/synthetic/onboarding/ready.json`  
Expected: exit 0 with `ready: true`.

Run: `python3 scripts/validate_plugin.py .`  
Expected: PASS with the four valid skill entrypoints.

- [ ] **Step 7: Commit readiness and activation**

```bash
git add src/career_pipeline skills/onboard scripts tests
git commit -m "feat: gate activation and safe discovery schedules"
```

---

### Task 5: Normalized sources and public ATS adapters

**Files:**
- Create: `schemas/job-candidate.schema.json`
- Create: `src/career_pipeline/sources/__init__.py`
- Create: `src/career_pipeline/sources/base.py`
- Create: `src/career_pipeline/sources/greenhouse.py`
- Create: `src/career_pipeline/sources/lever.py`
- Create: `src/career_pipeline/sources/ashby.py`
- Create: `src/career_pipeline/sources/generic.py`
- Create: `scripts/normalize_jobs.py`
- Create: `tests/unit/sources/test_greenhouse.py`
- Create: `tests/unit/sources/test_lever.py`
- Create: `tests/unit/sources/test_ashby.py`
- Create: `tests/unit/sources/test_generic.py`
- Create: `tests/fixtures/synthetic/postings/*.json`

**Interfaces:**
- Produces: `SourceSnapshot(source, fetched_at, records, cursor, success)`
- Produces: `normalize(snapshot: SourceSnapshot) -> list[CandidateJob]`
- `CandidateJob` requires source, source record ID, ATS/requisition ID when present, employer, exact title, responsibilities, location, workplace model, travel, compensation evidence, posting URL, application URL, posted/updated timestamps, and verification status.
- Consumes: schema validation from Task 2.

- [ ] **Step 1: Write adapter contract tests**

Create fictional Greenhouse, Lever, Ashby, Indeed-like, browser, and public-search snapshots. Assert consistent normalized fields, HTML cleanup, exact source attribution, distinct posting/application URLs, missing-field uncertainty, and no invented compensation or workplace model.

- [ ] **Step 2: Run source tests and verify failure**

Run: `python3 -m unittest discover -s tests/unit/sources -p 'test_*.py' -v`  
Expected: FAIL because the normalized source package is absent.

- [ ] **Step 3: Implement snapshot-only adapters**

Adapters transform retrieved payloads; they do not contain credentials, authenticated sessions, analytics, or hidden network calls. Public source retrieval remains a skill/tool concern. Preserve source record IDs and raw-field hashes so later runs can recognize changed requisitions without storing unnecessary full-page content.

- [ ] **Step 4: Add normalization CLI and schema validation**

Accept a source type plus input/output paths, write normalized JSON atomically, and report rejected records with source-local indexes. Never advance a checkpoint from this CLI.

- [ ] **Step 5: Run source verification**

Run: `python3 -m unittest discover -s tests/unit/sources -p 'test_*.py' -v`  
Expected: PASS for all four adapter families and missing-field cases.

- [ ] **Step 6: Commit source normalization**

```bash
git add schemas src/career_pipeline/sources scripts/normalize_jobs.py tests
git commit -m "feat: normalize synthetic ATS and connector job records"
```

---

### Task 6: Evidence-backed assessment, deduplication, and source checkpoints

**Files:**
- Create: `schemas/job-assessment.schema.json`
- Create: `src/career_pipeline/evaluation.py`
- Create: `src/career_pipeline/dedupe.py`
- Create: `src/career_pipeline/checkpoints.py`
- Create: `scripts/plan_discovery.py`
- Create: `tests/unit/test_evaluation.py`
- Create: `tests/unit/test_dedupe.py`
- Create: `tests/unit/test_checkpoints.py`
- Create: `tests/integration/test_cross_source_discovery.py`

**Interfaces:**
- Produces: `validate_assessment(job, profile, assessment) -> list[ValidationError]`
- Produces: `requisition_key(job) -> str | None`
- Produces: `fallback_fingerprint(job) -> str`
- Produces: `partition_candidates(candidates, existing) -> DiscoveryPartition`
- Produces: `complete_source(state, source, result) -> DiscoveryState`
- An assessment disposition is exactly `strong_match | worth_considering | non_match`.

- [ ] **Step 1: Write failing evaluation and dedupe tests**

Cover responsibility-first evaluation, evidence-supported strengths, explicit gaps, compensation/geography uncertainty, ATS-ID duplicates across sources, conservative company/title/location/team fallback, archived Linear records, changed requisitions, closed roles, and reposts.

```python
def test_same_requisition_across_sources_is_duplicate(self):
    ats = synthetic_job(source="greenhouse", requisition_id="SYN-204")
    broad = synthetic_job(source="public-search", requisition_id="SYN-204")
    self.assertEqual(requisition_key(ats), requisition_key(broad))

def test_failed_source_does_not_advance_checkpoint(self):
    before = synthetic_discovery_state()
    after = complete_source(before, "indeed", failed_source_result())
    self.assertEqual(after.sources["indeed"], before.sources["indeed"])
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python3 -m unittest tests.unit.test_evaluation tests.unit.test_dedupe tests.unit.test_checkpoints tests.integration.test_cross_source_discovery -v`  
Expected: FAIL because evaluation, dedupe, and checkpoint modules are absent.

- [ ] **Step 3: Implement validation and conservative identity**

Require every positive fit claim to reference a profile evidence identifier and every uncertainty to remain explicit. Prefer normalized ATS/requisition identity; otherwise normalize Unicode/case/spacing and hash employer, exact title, location, and team. Never collapse records solely because titles resemble one another.

- [ ] **Step 4: Implement independent checkpoint transitions**

A source advances its last-successful timestamp, seen-record set, and rotation cursor only after successful normalization and durable run evidence. Partial or failed lanes retain their prior checkpoint. Build a stable review-batch ID from ordered qualifying candidate keys.

- [ ] **Step 5: Run discovery-core verification**

Run: `python3 -m unittest tests.unit.test_evaluation tests.unit.test_dedupe tests.unit.test_checkpoints tests.integration.test_cross_source_discovery -v`  
Expected: PASS, including cross-source duplicates, closed/reposted roles, and failed checkpoints.

- [ ] **Step 6: Commit discovery core**

```bash
git add schemas src/career_pipeline scripts/plan_discovery.py tests
git commit -m "feat: add evidence checks dedupe and source checkpoints"
```

---

### Task 7: Linear delivery, Discover jobs, and Review backlog

**Files:**
- Create: `schemas/linear-delivery-receipt.schema.json`
- Create: `src/career_pipeline/linear_delivery.py`
- Modify: `skills/discover-jobs/SKILL.md`
- Create: `skills/discover-jobs/agents/openai.yaml`
- Create: `skills/discover-jobs/references/source-routing.md`
- Create: `skills/discover-jobs/references/evaluation-and-delivery.md`
- Modify: `skills/review-backlog/SKILL.md`
- Create: `skills/review-backlog/agents/openai.yaml`
- Create: `skills/review-backlog/references/backlog-actions.md`
- Create: `skills/discover-jobs/assets/Linear_Issue.template.md`
- Create: `scripts/build_linear_issue.py`
- Create: `scripts/record_linear_delivery.py`
- Create: `tests/unit/test_linear_delivery.py`
- Create: `tests/integration/test_discovery_delivery.py`
- Create: `tests/integration/test_review_backlog.py`
- Create: `tests/fixtures/synthetic/linear/*.json`

**Interfaces:**
- Consumes: candidates, assessments, dedupe keys, checkpoints, readiness, and configured Linear destination.
- Produces: `build_issue_payload(job, assessment, config) -> LinearIssuePayload`
- Produces: `verify_issue_readback(expected, actual) -> DeliveryReceipt`
- Produces: `record_delivery(state, receipt) -> DiscoveryState`
- Review backlog produces explicit `PacketSelection(ticket_ids, per_role_instructions)` only from the user's current request.

- [ ] **Step 1: Write failing Linear and backlog tests**

Use a fake Linear gateway. Assert exact required labels/views, final duplicate lookup immediately before create, archived-record coverage, readback before delivery state, all qualifying new roles delivered, non-matches kept local, unchanged runs quiet, and actionable source failures reported once.

- [ ] **Step 2: Run tests and confirm failure**

Run: `python3 -m unittest tests.unit.test_linear_delivery tests.integration.test_discovery_delivery tests.integration.test_review_backlog -v`  
Expected: FAIL because delivery and skill behavior are absent.

- [ ] **Step 3: Implement deterministic issue payloads and receipts**

Include every ticket field from the spec, stable source and re-verification timestamps, disposition label, exact URLs, uncertainty, and recommended next action. Compare created/read-back issue identity, labels, project/team, body hash, and URLs before producing a verified receipt.

- [ ] **Step 4: Write the Discover jobs skill**

Read only approved configuration/profile files; verify the Linear destination; build a duplicate baseline including archived records; route only through enabled and capability-tested lanes; retrieve public ATS content; normalize; verify original posting/application paths; assess responsibilities; deduplicate; perform a final Linear duplicate search; create/read back; then atomically commit checkpoints and the stable batch. Stay quiet when no actionable change exists.

- [ ] **Step 5: Write the Review backlog skill**

Support summaries, comparisons, deadlines, not-pursuing decisions, and one-or-many explicit ticket selections. Resolve exact ticket IDs and invoke immediate Prepare application work in the same conversation. State plainly that labels alone do not wake Codex and that no application is submitted.

- [ ] **Step 6: Verify Milestone 2**

Run: `python3 -m unittest discover -s tests -p 'test_*.py' -v`  
Expected: all shell, onboarding, source, discovery, and backlog tests PASS.

Run: `python3 scripts/validate_plugin.py .`  
Expected: PASS with the implemented Onboard, Discover jobs, and Review backlog skills plus the valid bounded Prepare application entrypoint.

Run: `python3 scripts/scan_private_data.py .`  
Expected: PASS.

- [ ] **Step 7: Commit discovery and backlog**

```bash
git add schemas src/career_pipeline skills/discover-jobs skills/review-backlog scripts tests
git commit -m "feat: deliver verified Linear backlog"
```

---

### Task 8: Versioned packet state and local artifact safety

**Files:**
- Create: `src/career_pipeline/packets.py`
- Create: `scripts/start_packet.py`
- Create: `scripts/update_packet.py`
- Create: `scripts/verify_packet_files.py`
- Create: `tests/unit/test_packets.py`
- Create: `tests/integration/test_packet_resumption.py`
- Create: `tests/fixtures/synthetic/packets/*.json`

**Interfaces:**
- Consumes: `WorkspacePaths`, atomic state, exact Linear ticket identity, and application manifest schema.
- Produces: `start_packet(ticket, workspace, options) -> PacketRecord`
- Produces: `advance_packet(manifest, ticket_id, stage, receipt) -> ApplicationManifest`
- Produces: `resume_queue(manifest) -> list[PacketRecord]`
- Produces: `verify_local_artifacts(record) -> ArtifactVerification`
- Packet stages are monotonic: `selected`, `posting_verified`, `drafted`, `quality_checked`, `saved`, `uploaded`, `delivery_verified`, `ready`.

- [ ] **Step 1: Write failing packet-path and state tests**

Assert `v001` allocation, sanitized ticket/company/role names, two employer-facing filenames directly in the version folder, private material only in `working/`, no overwrite of a prior version, monotonic transitions, artifact hashes, cover-letter opt-out, and safe restart after every stage.

```python
def test_final_pdfs_are_easy_to_find(self):
    record = start_packet(ticket("SYN-123"), workspace, default_options())
    self.assertEqual(record.version, "v001")
    self.assertEqual(record.resume_pdf.parent, record.version_dir)
    self.assertEqual(record.working_dir.parent, record.version_dir)

def test_resume_skips_verified_delivery(self):
    manifest = manifest_at("delivery_verified")
    self.assertEqual(resume_queue(manifest), [])
```

- [ ] **Step 2: Run packet-state tests and verify failure**

Run: `python3 -m unittest tests.unit.test_packets tests.integration.test_packet_resumption -v`  
Expected: FAIL because packet state handling is absent.

- [ ] **Step 3: Implement safe packet allocation and manifest transitions**

Use a deterministic safe-name policy with collision-resistant suffixes, allocate the next unused version while holding an atomic lock file, and never delete history. Require stage-specific receipts and file SHA-256 values. Make repeating the same transition idempotent and reject skips or conflicting receipts.

- [ ] **Step 4: Implement artifact verification CLI**

Require the final résumé PDF and the cover letter when enabled; forbid extra employer-facing files; verify nonzero size, magic bytes, recorded hash, and direct-parent placement. Keep all extracted text, render images, source snapshots, and review JSON under `working/`.

- [ ] **Step 5: Run packet-state verification**

Run: `python3 -m unittest tests.unit.test_packets tests.integration.test_packet_resumption -v`  
Expected: PASS at every interrupted stage and for multi-version history.

- [ ] **Step 6: Commit packet state**

```bash
git add src/career_pipeline scripts tests
git commit -m "feat: add resumable versioned packet storage"
```

---

### Task 9: Immediate application preparation and verified delivery

**Files:**
- Modify: `skills/prepare-application/SKILL.md`
- Create: `skills/prepare-application/agents/openai.yaml`
- Create: `skills/prepare-application/references/tailoring.md`
- Create: `skills/prepare-application/references/quality-gates.md`
- Create: `skills/prepare-application/references/linear-delivery.md`
- Create: `skills/prepare-application/assets/Resume.template.md`
- Create: `skills/prepare-application/assets/Cover_Letter.template.md`
- Create: `tests/integration/test_prepare_application.py`
- Create: `tests/e2e/test_immediate_packets.py`
- Create: `tests/fixtures/synthetic/profile/*.md`

**Interfaces:**
- Consumes: `PacketSelection`, packet state APIs, approved profile/writing files, verified Linear tickets, and Codex document/PDF capabilities.
- Produces: final résumé and optional cover-letter PDFs, quality receipts, Linear attachment receipts, one concise evidence/gap comment, and verified label transitions.
- The trigger contract is an explicit current user request containing exact ticket IDs or an explicit selection produced by Review backlog.

- [ ] **Step 1: Write failing immediate-workflow tests**

Use fake document, PDF, posting, and Linear gateways. Cover one ticket, multiple tickets, cover-letter opt-out, unavailable posting, factual mismatch, chronology conflict, page-count failure, visual failure, attachment mismatch, interrupted delivery, and “Resume my packet queue.” Assert work begins in the same invocation and no scheduler call exists.

- [ ] **Step 2: Run application tests and verify failure**

Run: `python3 -m unittest tests.integration.test_prepare_application tests.e2e.test_immediate_packets -v`  
Expected: FAIL because the Prepare application skill is absent.

- [ ] **Step 3: Write tailoring and quality references**

Rank accomplishments by relevance, impact, contribution, scope, distinctiveness, recency, factual support, and rendered space. Require a two-page text-focused ATS-friendly résumé and, by default, a one-page cover letter. Require factual, chronology, tailoring, ATS structure, page-space, extracted-PDF-text, page-count, and rendered visual checks. Apply ATS-specific rules only after verifying the real destination.

- [ ] **Step 4: Write the immediate Prepare application skill**

Resolve tickets and add `Prepare application`; begin work immediately; re-verify posting and application URL; load current approved evidence and per-role instructions; generate documents with the Codex document/PDF capabilities; run every gate; save and hash final PDFs; upload those exact bytes; read attachments back; add one concise comment; set `Packet ready`; and clear `Prepare application` only after verified delivery. Never infer submission and never schedule this workflow.

- [ ] **Step 5: Implement idempotent multi-role and resume behavior**

Process each explicitly selected ticket independently, preserving a manifest entry and failure reason per ticket. On resume, continue from the latest verified stage and reuse matching hashes; do not duplicate versions, attachments, comments, or labels. If the current profile hash differs, stop and ask whether to restart the affected draft as a new version.

- [ ] **Step 6: Verify Milestone 3**

Run: `python3 -m unittest discover -s tests -p 'test_*.py' -v`  
Expected: all tests PASS, including immediate single/multi-role and every interruption stage.

Run: `python3 scripts/validate_plugin.py .`  
Expected: PASS with exactly four valid skills.

Run: `python3 scripts/scan_private_data.py .`  
Expected: PASS.

- [ ] **Step 7: Commit immediate packets**

```bash
git add skills/prepare-application tests
git commit -m "feat: prepare and deliver application packets immediately"
```

---

### Task 10: Optional lifecycle reconciliation

**Files:**
- Create: `schemas/lifecycle-receipt.schema.json`
- Create: `src/career_pipeline/reconciliation.py`
- Create: `skills/onboard/references/lifecycle-reconciliation.md`
- Modify: `skills/onboard/assets/lifecycle-automation-prompt.md`
- Create: `scripts/record_lifecycle_evidence.py`
- Create: `tests/unit/test_reconciliation.py`
- Create: `tests/integration/test_lifecycle_automation.py`
- Create: `tests/fixtures/synthetic/lifecycle/*.json`

**Interfaces:**
- Consumes: opted-in Gmail/Calendar capabilities, configured Linear project, exact-role lookup, and lifecycle schema.
- Produces: `classify_lifecycle_evidence(evidence, candidates) -> LifecycleDecision`
- Decision values: `apply_update`, `needs_review`, or `ignore`.
- Produces a minimal receipt with source kind, source-local opaque ID/hash, timestamp, matched ticket, evidence class, decision, and resulting Linear readback; it never stores full mailbox or calendar bodies.

- [ ] **Step 1: Write failing lifecycle tests**

Cover exact confirmations, rejections, interview invitations, offers, ambiguous recruiter messages, employer-generic messages, contradictory messages, wrong-role matches, connector decline, read-only capability, and duplicate unchanged evidence.

- [ ] **Step 2: Run lifecycle tests and verify failure**

Run: `python3 -m unittest tests.unit.test_reconciliation tests.integration.test_lifecycle_automation -v`  
Expected: FAIL because reconciliation is absent.

- [ ] **Step 3: Implement conservative evidence decisions**

Require exact employer plus role/requisition identity and one unambiguous event class before an automatic Linear update. Route ambiguity or contradiction to user review. Deduplicate on source-local opaque ID/hash. Record only the minimum receipt and preserve connector permission limits.

- [ ] **Step 4: Finalize the optional weekday automation prompt**

Offer one weekday check in the user's timezone only when Gmail or Calendar is enabled. The prompt reads job-related evidence, writes only derived clear status to Linear after readback, and remains quiet when unchanged. It cannot send/reply, accept invitations, create events, or contact anyone.

- [ ] **Step 5: Run lifecycle verification**

Run: `python3 -m unittest tests.unit.test_reconciliation tests.integration.test_lifecycle_automation -v`  
Expected: PASS for clear, ambiguous, contradictory, declined, and repeated evidence.

- [ ] **Step 6: Commit lifecycle reconciliation**

```bash
git add schemas src/career_pipeline skills/onboard scripts tests
git commit -m "feat: add conservative lifecycle reconciliation"
```

---

### Task 11: Backed-up migrations and update safety

**Files:**
- Create: `src/career_pipeline/migrations.py`
- Create: `scripts/migrate_workspace.py`
- Create: `tests/unit/test_migrations.py`
- Create: `tests/integration/test_plugin_update.py`
- Create: `tests/fixtures/synthetic/migrations/v1/*.json`
- Create: `docs/UPGRADING.md`

**Interfaces:**
- Consumes: schema versions and atomic state APIs.
- Produces: `plan_migration(workspace, target_version) -> MigrationPlan`
- Produces: `apply_migration(plan, confirmation_token) -> MigrationReceipt`
- A plan lists exact state files, backup directory, source/target versions, reversible operations, and application-history invariants.

- [ ] **Step 1: Write failing migration tests**

Assert dry-run by default, explicit confirmation token, backup-before-write, rollback after simulated interruption, rejection of unknown future versions, preservation of original résumé and all application versions, and no change to Linear history.

- [ ] **Step 2: Run migration tests and verify failure**

Run: `python3 -m unittest tests.unit.test_migrations tests.integration.test_plugin_update -v`  
Expected: FAIL because migration support is absent.

- [ ] **Step 3: Implement migration planning and application**

Write backups beneath the user's `State/backups/<timestamp>/`, hash every input and backup, migrate only known schema documents, and atomically write a receipt. Separate plugin version from workspace schema version so plugin updates never rewrite user content merely because package semver changed.

- [ ] **Step 4: Document safe updates**

Explain private-beta update/reinstall, new-thread pickup, readiness recheck, migration confirmation, backup locations, and recovery. Do not put any user-specific installation path or private repository URL in the document.

- [ ] **Step 5: Run migration verification**

Run: `python3 -m unittest tests.unit.test_migrations tests.integration.test_plugin_update -v`  
Expected: PASS, including interrupted migration rollback and intact packet history.

- [ ] **Step 6: Commit migration safety**

```bash
git add src/career_pipeline scripts tests docs/UPGRADING.md
git commit -m "feat: add backed-up workspace migrations"
```

---

### Task 12: Synthetic end-to-end beta gate and private packaging

**Files:**
- Create: `tests/e2e/test_private_beta.py`
- Create: `tests/fixtures/synthetic/README.md`
- Create: `scripts/package_plugin.py`
- Create: `README.md`
- Create: `PRIVACY.md`
- Create: `SECURITY.md`
- Create: `docs/BETA_TESTING.md`
- Create: `CHANGELOG.md`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: all prior runtime, skill, schema, fixture, migration, and validation interfaces.
- Produces: `dist/career-pipeline-0.1.0.zip` from an explicit inclusion list.
- Produces: a machine-readable `dist/career-pipeline-0.1.0.sha256`.
- Produces: a manual private-beta acceptance checklist requiring no telemetry or automatic feedback.

- [ ] **Step 1: Write the complete synthetic beta test**

Run a fictional user through complete and resumed onboarding, each optional connector choice, Linear gating, discovery across all three ATS adapters and duplicate broad sources, qualifying/non-qualifying delivery, backlog comparison, immediate single/multi-role packets, interrupted resume, clear/ambiguous lifecycle evidence, and migration. Assert final PDFs are directly under the synthetic `Applications/` version folders and no scheduler receives packet work.

- [ ] **Step 2: Run the full suite before packaging**

Run: `python3 -m unittest discover -s tests -p 'test_*.py' -v`  
Expected: PASS with no network access and only temporary synthetic workspaces.

- [ ] **Step 3: Implement reproducible packaging**

Include only `.codex-plugin/`, `skills/`, `src/`, `scripts/`, `schemas/`, and approved top-level documentation required at runtime/distribution. Exclude `.git/`, tests, caches, local environments, generated workspaces, documents, PDFs, secrets, and `dist/`. Normalize archive timestamps and ordering, then emit SHA-256.

- [ ] **Step 4: Write beta documentation**

Document private installation/share flow, “Set up my job search,” required Linear behavior, optional connector choices, local workspace ownership, immediate packet trigger examples, `Applications/` locations, no auto-apply/send behavior, no telemetry, manual feedback, upgrade safety, and three-to-five-user acceptance steps. Use only generic placeholders such as `JOB-123`, `Example Company`, and `Example Role`.

- [ ] **Step 5: Run all release gates**

Run: `python3 scripts/scan_private_data.py .`  
Expected: PASS with zero findings.

Run: `python3 scripts/validate_plugin.py .`  
Expected: PASS with exactly four user-facing skills and no custom app/MCP declaration.

Run: `python3 -m unittest discover -s tests -p 'test_*.py' -v`  
Expected: PASS.

Run: `python3 scripts/package_plugin.py --version 0.1.0`  
Expected: creates the archive and checksum deterministically.

Run: `python3 scripts/scan_private_data.py dist/career-pipeline-0.1.0.zip`  
Expected: PASS after scanning archive members.

Run the current Codex plugin validator supplied by the plugin-creation tooling against the repository root.  
Expected: PASS.

- [ ] **Step 6: Inspect the package and Git boundary**

Run: `python3 -m zipfile -l dist/career-pipeline-0.1.0.zip`  
Expected: only the explicit distribution files; no fixtures, generated workspace, application material, environment file, absolute path, or Git metadata.

Run: `git remote -v`  
Expected: no remote until a private destination is deliberately configured.

Run: `git status --short`  
Expected: no unexpected tracked or untracked files; the ignored `dist/` artifact does not appear.

- [ ] **Step 7: Verify Milestone 4 and commit the beta candidate**

```bash
git add README.md PRIVACY.md SECURITY.md CHANGELOG.md docs pyproject.toml src scripts schemas skills tests
git commit -m "release: prepare career pipeline private beta 0.1.0"
```

## Final acceptance checklist

- [ ] A nontechnical Codex Desktop user can install the archive and complete onboarding conversationally.
- [ ] Linear is required and verified; each optional connector can be declined independently with an accurate fallback.
- [ ] Profile and search-criteria approval gates activation.
- [ ] Discovery is schedulable; packet creation is absent from every automation path.
- [ ] Strong Match and Worth Considering roles are deduplicated, delivered, and read back in Linear; clear non-matches stay local.
- [ ] Explicit one- and multi-ticket packet requests begin immediately.
- [ ] Verified final PDFs are attached in Linear and directly browseable under the local `Applications/` folder.
- [ ] Interrupted workflows resume without duplicate issues, versions, attachments, comments, or alerts.
- [ ] Lifecycle updates occur only from exact, unambiguous evidence or explicit user direction.
- [ ] Updates back up state and preserve the source résumé, application history, and Linear history.
- [ ] Repository and archive privacy scans find no personal data, résumé/application content, credential, telemetry code, private URL, or developer-specific path.
- [ ] The plugin has no developer-operated service and produces no automatic feedback or logs.
