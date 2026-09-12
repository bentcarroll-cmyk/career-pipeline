from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from career_pipeline.automation_policy import UnsupportedAutomation, render_automation
from career_pipeline.backlog import (
    compare_jobs,
    mark_not_pursuing,
    selection_from_request,
)
from career_pipeline.checkpoints import DiscoveryState
from career_pipeline.discovery import ReviewedJob, deliver_reviewed_jobs
from career_pipeline.evaluation import EvidenceClaim, JobAssessment
from career_pipeline.exports import record_verified_export
from career_pipeline.indexes import load_indexes
from career_pipeline.job_store import read_job
from career_pipeline.linear_delivery import (
    ExportVerificationError,
    build_linear_export_payload,
    verify_linear_export_readback,
)
from career_pipeline.migrations import apply_migration, plan_migration
from career_pipeline.onboarding import (
    CONNECTORS,
    OnboardingState,
    advance_onboarding,
    load_onboarding_state,
    record_connector_decision,
    record_profile_approval,
    save_onboarding_state,
)
from career_pipeline.packets import (
    ApplicationManifest,
    PacketOptions,
    advance_packet,
    collect_local_artifacts,
    complete_local_delivery,
    load_manifest,
    restart_packet,
    resume_queue,
    save_manifest,
    start_packet,
)
from career_pipeline.quality import QualityReceipt
from career_pipeline.readiness import check_readiness
from career_pipeline.reconciliation import (
    LifecycleEvidence,
    reconcile_lifecycle_evidence,
)
from career_pipeline.sources.base import SourceSnapshot
from career_pipeline.sources.generic import normalize as normalize_generic
from career_pipeline.sources.greenhouse import normalize as normalize_greenhouse
from career_pipeline.workspace import create_workspace, preserve_source_resume
from tests.pdf_helper import write_minimal_pdf
from tests.unit.test_packets import bound_quality_receipt, synthetic_packet_options


FIXTURES = (
    Path(__file__).resolve().parents[1] / "fixtures" / "synthetic" / "postings"
)


def _assessment(
    disposition: str = "strong_match",
    *,
    profile_hash: str,
    criteria_hash: str,
) -> JobAssessment:
    strengths = (
        (EvidenceClaim("EV-SYN-001", "Led a fictional operating cadence."),)
        if disposition != "non_match"
        else ()
    )
    return JobAssessment(
        disposition=disposition,
        role_to_profile_fit="Synthetic evidence was evaluated against the role.",
        strengths=strengths,
        gaps=("A fictional domain gap needs confirmation.",),
        uncertainties=("Travel expectations are not stated.",),
        profile_hash=profile_hash,
        criteria_hash=criteria_hash,
    )


def _reviewed(
    candidate,
    disposition: str = "strong_match",
    *,
    profile_hash: str,
    criteria_hash: str,
) -> ReviewedJob:
    return ReviewedJob(
        candidate=candidate,
        assessment=_assessment(
            disposition,
            profile_hash=profile_hash,
            criteria_hash=criteria_hash,
        ),
        posting_markdown="# Synthetic posting\n\nNo real opportunity data.\n",
        assessment_markdown="# Synthetic assessment\n\nNo real person data.\n",
    )


def _finish_packet(workspace, manifest, job_id, occurred_at):
    record = manifest.packets[job_id][-1]
    resume = workspace.root / record.resume_pdf
    write_minimal_pdf(resume, pages=2)
    if record.cover_letter_pdf is not None:
        cover_letter = workspace.root / record.cover_letter_pdf
        write_minimal_pdf(cover_letter, pages=1)
    artifact_hashes = collect_local_artifacts(workspace, record).hashes
    if record.stage == "selected":
        manifest = advance_packet(
            manifest,
            job_id,
            "posting_verified",
            {
                "posting_url": "https://jobs.example/postings/SYNTHETIC",
                "application_url": "https://jobs.example/apply/SYNTHETIC",
                "posting_snapshot_hash": "b" * 64,
            },
        )
    if manifest.packets[job_id][-1].stage == "posting_verified":
        manifest = advance_packet(
            manifest,
            job_id,
            "drafted",
            {"draft_hashes": {name: "a" * 64 for name in artifact_hashes}},
        )
    if manifest.packets[job_id][-1].stage == "drafted":
        manifest = advance_packet(
            manifest,
            job_id,
            "quality_checked",
            bound_quality_receipt(
                manifest.packets[job_id][-1], artifact_hashes
            ),
        )
    if manifest.packets[job_id][-1].stage == "quality_checked":
        manifest = advance_packet(
            manifest,
            job_id,
            "saved",
            {"artifact_hashes": artifact_hashes},
        )
    return complete_local_delivery(
        workspace,
        manifest,
        job_id,
        occurred_at=occurred_at,
    )


class PrivateBetaTests(unittest.TestCase):
    def test_complete_local_first_private_beta_journey(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            profile = workspace.profile / "Career_Profile.md"
            criteria = workspace.profile / "Search_Criteria.md"
            profile.write_text(
                "Synthetic approved profile\n\nEV-SYN-001: Fictional evidence.\n",
                encoding="utf-8",
            )
            criteria.write_text("Synthetic approved criteria\n", encoding="utf-8")
            (workspace.profile / "Writing_Preferences.md").write_text(
                "Synthetic writing preferences\n",
                encoding="utf-8",
            )
            source_resume = Path(raw) / "Synthetic_Resume.txt"
            source_resume.write_text("Synthetic source résumé\n", encoding="utf-8")
            resume = preserve_source_resume(source_resume, workspace).destination

            onboarding = OnboardingState()
            onboarding = advance_onboarding(onboarding, "workspace", {"approved": True})
            onboarding = advance_onboarding(
                onboarding,
                "connectors",
                {"workspace_created": True},
            )
            for connector in CONNECTORS:
                onboarding = record_connector_decision(
                    onboarding,
                    connector,
                    "declined",
                    (),
                )
            onboarding = advance_onboarding(
                onboarding,
                "resume",
                {"all_connector_decisions_recorded": True},
            )
            onboarding_path = workspace.state / "onboarding-state.json"
            save_onboarding_state(onboarding_path, onboarding)
            onboarding = load_onboarding_state(onboarding_path)
            onboarding = advance_onboarding(
                onboarding,
                "interview",
                {"resume_preserved": True},
            )
            onboarding = advance_onboarding(
                onboarding,
                "profile",
                {"interview_complete": True},
            )
            onboarding = record_profile_approval(
                onboarding,
                hashlib.sha256(profile.read_bytes()).hexdigest(),
                hashlib.sha256(criteria.read_bytes()).hexdigest(),
            )
            for stage, receipt in (
                ("packet_defaults", {"profile_approved": True}),
                ("schedule", {"packet_defaults_approved": True}),
                ("readiness", {"schedule_decided": True}),
            ):
                onboarding = advance_onboarding(onboarding, stage, receipt)
            config = {
                "schema_version": 2,
                "workspace_root": str(workspace.root),
                "timezone": "America/New_York",
                "enabled_sources": ["public_ats"],
                "discovery_schedule": {
                    "frequency": "weekday",
                    "weekdays": ["MO", "TU", "WE", "TH", "FR"],
                    "runs_per_day": 2,
                    "timezone": "America/New_York",
                },
                "paths": {
                    "profile": "Profile",
                    "sources": "Sources",
                    "jobs": "Jobs",
                    "applications": "Applications",
                    "indexes": "Indexes",
                    "runs": "Runs",
                    "state": "State",
                },
                "profile_approved": True,
                "criteria_approved": True,
                "connectors": {
                    name: {"decision": "declined", "capabilities": []}
                    for name in CONNECTORS
                },
                "packet_defaults": {
                    "resume_pages": 2,
                    "cover_letter_enabled": True,
                    "cover_letter_pages": 1,
                },
            }
            (workspace.state / "config.json").write_text(
                json.dumps(config), encoding="utf-8"
            )
            save_onboarding_state(onboarding_path, onboarding)
            readiness = check_readiness(config, onboarding)
            self.assertTrue(readiness.ready, readiness.failure_codes)
            onboarding = advance_onboarding(
                onboarding,
                "active",
                {"ready": readiness.ready},
            )
            self.assertEqual(onboarding.stage, "active")
            self.assertTrue(
                all(status.decision == "declined" for status in onboarding.connectors.values())
            )

            greenhouse_raw = json.loads(
                (FIXTURES / "greenhouse.json").read_text(encoding="utf-8")
            )
            generic_raw = json.loads(
                (FIXTURES / "generic.json").read_text(encoding="utf-8")
            )
            greenhouse = normalize_greenhouse(
                SourceSnapshot(
                    "greenhouse",
                    "2026-09-11T12:00:00Z",
                    greenhouse_raw,
                )
            )[0]
            generic = normalize_generic(
                SourceSnapshot(
                    "public-search",
                    "2026-09-11T12:01:00Z",
                    generic_raw,
                )
            )[0]
            duplicate = replace(
                greenhouse,
                source="public-search",
                source_record_id="synthetic-duplicate-record",
                raw_field_hash="d" * 64,
            )
            non_match = replace(
                generic,
                source_record_id="synthetic-non-match-record",
                requisition_id="SYN-NON-999",
                title="Synthetic Non-Match Role",
                raw_field_hash="e" * 64,
            )
            discovery = deliver_reviewed_jobs(
                workspace,
                DiscoveryState(),
                (
                    _reviewed(greenhouse, profile_hash=onboarding.profile_hash, criteria_hash=onboarding.criteria_hash),
                    _reviewed(duplicate, profile_hash=onboarding.profile_hash, criteria_hash=onboarding.criteria_hash),
                    _reviewed(generic, "worth_considering", profile_hash=onboarding.profile_hash, criteria_hash=onboarding.criteria_hash),
                    _reviewed(non_match, "non_match", profile_hash=onboarding.profile_hash, criteria_hash=onboarding.criteria_hash),
                ),
                occurred_at="2026-09-11T12:05:00Z",
            )
            self.assertEqual(discovery.created_job_ids, ("JOB-000001", "JOB-000002"))
            self.assertEqual(len(discovery.duplicate_keys), 1)
            self.assertEqual(len(discovery.non_match_keys), 1)
            backlog = load_indexes(workspace).backlog
            self.assertEqual(
                [item["job_id"] for item in backlog["jobs"]],
                ["JOB-000001", "JOB-000002"],
            )

            compared = compare_jobs(workspace, discovery.created_job_ids)
            self.assertEqual(len(compared), 2)
            declined = mark_not_pursuing(
                workspace,
                "JOB-000002",
                occurred_at="2026-09-11T12:10:00Z",
            )
            self.assertEqual(declined["status"], "not_pursuing")

            selection = selection_from_request(
                discovery.created_job_ids,
                {"JOB-000002": "Use only fictional evidence."},
                explicit_request=True,
                workspace=workspace,
            )
            manifest = ApplicationManifest()
            manifest, first = start_packet(
                workspace,
                "JOB-000001",
                synthetic_packet_options(role_instructions=""),
                manifest,
                occurred_at="2026-09-11T12:15:00Z",
                explicit_request=True,
            )
            self.assertEqual(first.stage, "selected")
            self.assertEqual(read_job(workspace, "JOB-000001")["status"], "prepare_application")
            manifest, second = start_packet(
                workspace,
                "JOB-000002",
                synthetic_packet_options(
                    cover_letter_enabled=True,
                    cover_letter_pages=1,
                    role_instructions=selection.per_role_instructions["JOB-000002"],
                ),
                manifest,
                occurred_at="2026-09-11T12:16:00Z",
                explicit_request=True,
            )
            self.assertEqual(set(manifest.packets), set(selection.job_ids))
            manifest = _finish_packet(
                workspace,
                manifest,
                "JOB-000001",
                "2026-09-11T12:20:00Z",
            )
            manifest = advance_packet(
                manifest,
                "JOB-000002",
                "posting_verified",
                {
                    "posting_url": "https://jobs.example/postings/SYN-PUB-404",
                    "application_url": "https://jobs.example/apply/SYN-PUB-404",
                    "posting_snapshot_hash": "b" * 64,
                },
            )
            manifest_path = workspace.state / "application-manifest.json"
            save_manifest(manifest_path, manifest)
            manifest = load_manifest(manifest_path)
            self.assertEqual(
                [record.job_id for record in resume_queue(manifest)],
                ["JOB-000002"],
            )
            manifest = _finish_packet(
                workspace,
                manifest,
                "JOB-000002",
                "2026-09-11T12:21:00Z",
            )
            self.assertEqual(resume_queue(manifest), ())
            for record in (first, second):
                self.assertEqual((workspace.root / record.resume_pdf).parent, workspace.root / record.version_dir)

            manifest, single = restart_packet(
                workspace,
                "JOB-000001",
                synthetic_packet_options(
                    cover_letter_enabled=True,
                    cover_letter_pages=1,
                    role_instructions="",
                ),
                manifest,
                occurred_at="2026-09-11T12:25:00Z",
                explicit_request=True,
            )
            self.assertEqual(single.version, "v002")
            manifest = _finish_packet(
                workspace,
                manifest,
                "JOB-000001",
                "2026-09-11T12:30:00Z",
            )
            self.assertEqual((workspace.root / single.resume_pdf).parent, workspace.root / single.version_dir)
            self.assertEqual((workspace.root / single.cover_letter_pdf).parent, workspace.root / single.version_dir)
            with self.assertRaises(UnsupportedAutomation):
                render_automation(
                    "application-packet",
                    {
                        "workspace_config": "State/config.json",
                        "timezone": "America/New_York",
                    },
                )

            clear = reconcile_lifecycle_evidence(
                workspace,
                LifecycleEvidence(
                    source_kind="gmail",
                    opaque_id="synthetic-message-clear",
                    observed_at="2026-09-11T12:35:00Z",
                    employer="Northstar Example Cooperative",
                    role_title="Director of Operations",
                    requisition_id="SYN-GH-101",
                    event_class="application_confirmation",
                ),
                enabled_sources=("gmail",),
            )
            ambiguous = reconcile_lifecycle_evidence(
                workspace,
                LifecycleEvidence(
                    source_kind="gmail",
                    opaque_id="synthetic-message-ambiguous",
                    observed_at="2026-09-11T12:36:00Z",
                    employer="Atlas Example Group",
                    role_title=None,
                    requisition_id=None,
                    event_class="interview_invitation",
                ),
                enabled_sources=("gmail",),
            )
            self.assertEqual(clear.decision.action, "apply_update")
            self.assertEqual(ambiguous.decision.action, "needs_review")
            self.assertEqual(read_job(workspace, "JOB-000001")["status"], "applied")
            self.assertEqual(read_job(workspace, "JOB-000002")["status"], "not_pursuing")
            self.assertEqual(
                read_job(workspace, "JOB-000002")["application_versions"][0]["version"],
                "v001",
            )

            export_payload = build_linear_export_payload(
                workspace,
                "JOB-000001",
                {"team_id": "synthetic-team", "project_id": "synthetic-project"},
                explicit_request=True,
            )
            before_failure = read_job(workspace, "JOB-000001")
            with self.assertRaises(ExportVerificationError):
                verify_linear_export_readback(
                    export_payload,
                    {**export_payload.to_readback("SYN-EXPORT-1"), "title": "mismatch"},
                    exported_at="2026-09-11T12:40:00Z",
                )
            self.assertEqual(read_job(workspace, "JOB-000001"), before_failure)
            export_receipt = verify_linear_export_readback(
                export_payload,
                export_payload.to_readback("SYN-EXPORT-2"),
                exported_at="2026-09-11T12:41:00Z",
            )
            exported = record_verified_export(
                workspace,
                "JOB-000001",
                export_receipt,
                explicit_request=True,
            )
            self.assertEqual(exported["status"], "applied")
            self.assertEqual(len(exported["exports"]), 1)

            canonical_before_rebuild = {
                path.relative_to(workspace.jobs): path.read_bytes()
                for path in workspace.jobs.rglob("*")
                if path.is_file()
            }
            (workspace.indexes / "backlog.json").unlink()
            (workspace.indexes / "deduplication.json").write_text(
                "corrupt synthetic index",
                encoding="utf-8",
            )
            regenerated = load_indexes(workspace)
            self.assertEqual(len(regenerated.backlog["jobs"]), 2)
            self.assertEqual(
                {
                    path.relative_to(workspace.jobs): path.read_bytes()
                    for path in workspace.jobs.rglob("*")
                    if path.is_file()
                },
                canonical_before_rebuild,
            )

            config_path = workspace.state / "config.json"
            prototype_config = {
                "schema_version": 1,
                "timezone": "America/New_York",
                "linear": {
                    "workspace_id": "synthetic-workspace",
                    "team_id": "synthetic-team",
                    "project_id": "synthetic-project",
                },
            }
            config_path.write_text(
                json.dumps(prototype_config, sort_keys=True),
                encoding="utf-8",
            )
            preserved_resume = resume.read_bytes()
            preserved_packets = {
                path.relative_to(workspace.applications): path.read_bytes()
                for path in workspace.applications.rglob("*")
                if path.is_file()
            }
            plan = plan_migration(workspace)
            apply_migration(plan, plan.confirmation_token)
            self.assertTrue((plan.backup_dir / "config.json").is_file())
            self.assertEqual(resume.read_bytes(), preserved_resume)
            self.assertEqual(
                {
                    path.relative_to(workspace.applications): path.read_bytes()
                    for path in workspace.applications.rglob("*")
                    if path.is_file()
                },
                preserved_packets,
            )
            self.assertEqual(
                json.loads(config_path.read_text(encoding="utf-8"))["schema_version"],
                2,
            )


if __name__ == "__main__":
    unittest.main()
