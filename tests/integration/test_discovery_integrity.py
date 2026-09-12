from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from career_pipeline.atomic import atomic_write_json
from career_pipeline.checkpoints import DiscoveryState
from career_pipeline.criteria import (
    CriteriaRule,
    SearchCriteria,
    approve_workspace_criteria,
    criteria_to_mapping,
)
from career_pipeline.discovery import AssessmentBatchError, ReviewedJob, deliver_reviewed_jobs
from career_pipeline.evaluation import EvidenceClaim, JobAssessment
from career_pipeline.job_store import read_job, update_job_status
from career_pipeline.onboarding import OnboardingState, save_onboarding_state
from career_pipeline.sources.base import CandidateJob
from career_pipeline.workspace import create_workspace


def approve_inputs(workspace, *, criteria_text: str = "Approved criteria v1") -> tuple[str, str]:
    profile = workspace.profile / "Career_Profile.md"
    criteria = workspace.profile / "Search_Criteria.md"
    profile.write_text("# Career profile\n\n- EV-010: Synthetic operations evidence.\n", encoding="utf-8")
    criteria.write_text(criteria_text + "\n", encoding="utf-8")
    profile_hash = hashlib.sha256(profile.read_bytes()).hexdigest()
    criteria_hash = hashlib.sha256(criteria.read_bytes()).hexdigest()
    save_onboarding_state(
        workspace.state / "onboarding-state.json",
        OnboardingState(profile_hash=profile_hash, criteria_hash=criteria_hash),
    )
    return profile_hash, criteria_hash


def install_location_exclusion(workspace) -> tuple[SearchCriteria, tuple[str, str]]:
    hashes = approve_inputs(workspace)
    criteria = SearchCriteria(
        "Profile/Search_Criteria.md",
        hashes[1],
        (
            CriteriaRule(
                criterion_id="location-approved",
                dimension="location",
                subject="job_location",
                classification="hard_exclusion",
                operator="one_of",
                reason_code="location_outside_approved_area",
                user_confirmed=True,
                values=("Remote",),
            ),
        ),
    )
    atomic_write_json(
        workspace.profile / "Search_Criteria.json",
        criteria_to_mapping(criteria),
    )
    approve_workspace_criteria(
        workspace,
        expected_readable_sha256=hashes[1],
        expected_structured_sha256=criteria.structured_sha256,
    )
    return criteria, hashes


def candidate(
    requisition_id: str | None,
    *,
    record_id: str,
    content_hash: str = "a" * 64,
    verified_at: str = "2026-09-11T12:00:00Z",
) -> CandidateJob:
    return CandidateJob(
        source="public-search",
        source_record_id=record_id,
        requisition_id=requisition_id,
        employer="Example Cooperative",
        title="Operations Lead",
        responsibilities=("Lead a fictional operating cadence.",),
        location="Example City",
        workplace_model="hybrid",
        travel=None,
        compensation_evidence=None,
        posting_url=f"https://jobs.example/{record_id}",
        application_url=f"https://jobs.example/{record_id}/apply",
        team="Operations",
        posted_at=None,
        updated_at=None,
        deadline=None,
        verified_at=verified_at,
        verification_status="verified",
        raw_field_hash=content_hash,
        uncertainties=("travel", "compensation"),
    )


def reviewed(job: CandidateJob, hashes: tuple[str, str], *, disposition: str = "strong_match", fit: str = "Fit v1") -> ReviewedJob:
    return ReviewedJob(
        job,
        JobAssessment(
            disposition=disposition,
            role_to_profile_fit=fit,
            strengths=(EvidenceClaim("EV-010", "Led fictional operations."),) if disposition != "non_match" else (),
            gaps=("Synthetic gap.",),
            uncertainties=("Travel is unstated.",),
            reason_codes=("responsibilities_do_not_align",) if disposition == "non_match" else (),
            profile_hash=hashes[0],
            criteria_hash=hashes[1],
        ),
        posting_markdown="# Synthetic posting\n",
        assessment_markdown=f"# {fit}\n",
    )


class DiscoveryIntegrityTests(unittest.TestCase):
    def test_fallback_then_requisition_enriches_same_canonical_job(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            hashes = approve_inputs(workspace)
            first = deliver_reviewed_jobs(
                workspace, DiscoveryState(), (reviewed(candidate(None, record_id="fallback"), hashes),),
                occurred_at="2026-09-11T12:01:00Z",
            )
            second = deliver_reviewed_jobs(
                workspace, first.state, (reviewed(candidate("REQ-10", record_id="stable", content_hash="b" * 64, verified_at="2026-09-11T13:00:00Z"), hashes),),
                occurred_at="2026-09-11T13:01:00Z",
            )
            self.assertEqual(second.created_job_ids, ())
            self.assertEqual(read_job(workspace, "JOB-000001")["requisition_id"], "REQ-10")
            self.assertEqual(len(list(workspace.jobs.iterdir())), 1)

    def test_requisition_then_fallback_reuses_same_canonical_job_without_erasing_identity(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            hashes = approve_inputs(workspace)
            first = deliver_reviewed_jobs(
                workspace, DiscoveryState(), (reviewed(candidate("REQ-10", record_id="stable"), hashes),),
                occurred_at="2026-09-11T12:01:00Z",
            )
            second = deliver_reviewed_jobs(
                workspace, first.state, (reviewed(candidate(None, record_id="fallback", content_hash="b" * 64, verified_at="2026-09-11T13:00:00Z"), hashes),),
                occurred_at="2026-09-11T13:01:00Z",
            )
            self.assertEqual(second.created_job_ids, ())
            self.assertEqual(read_job(workspace, "JOB-000001")["requisition_id"], "REQ-10")
            self.assertEqual(len(list(workspace.jobs.iterdir())), 1)

    def test_distinct_known_requisitions_survive_same_fallback_and_missing_identity_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            hashes = approve_inputs(workspace)
            state = DiscoveryState()
            for number in (1, 2):
                outcome = deliver_reviewed_jobs(
                    workspace, state, (reviewed(candidate(f"REQ-{number}", record_id=f"known-{number}"), hashes),),
                    occurred_at=f"2026-09-11T12:0{number}:00Z",
                )
                state = outcome.state
            ambiguous = deliver_reviewed_jobs(
                workspace, state, (reviewed(candidate(None, record_id="unknown"), hashes),),
                occurred_at="2026-09-11T12:03:00Z",
            )
            self.assertEqual(len(list(workspace.jobs.iterdir())), 2)
            self.assertEqual(ambiguous.created_job_ids, ())
            self.assertEqual(len(ambiguous.duplicate_keys), 1)

    def test_identity_resolution_refreshes_after_each_batch_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            hashes = approve_inputs(workspace)
            seeded = deliver_reviewed_jobs(
                workspace,
                DiscoveryState(),
                (reviewed(candidate(None, record_id="fallback"), hashes),),
                occurred_at="2026-09-11T12:01:00Z",
            )

            outcome = deliver_reviewed_jobs(
                workspace,
                seeded.state,
                (
                    reviewed(candidate("REQ-1", record_id="known-1"), hashes),
                    reviewed(candidate("REQ-2", record_id="known-2"), hashes),
                ),
                occurred_at="2026-09-11T13:01:00Z",
            )

            self.assertEqual(outcome.created_job_ids, ("JOB-000002",))
            self.assertEqual(read_job(workspace, "JOB-000001")["requisition_id"], "REQ-1")
            self.assertEqual(read_job(workspace, "JOB-000002")["requisition_id"], "REQ-2")

    def test_hard_filtered_supplied_assessment_is_validated_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            initial_hashes = approve_inputs(workspace)
            initial = deliver_reviewed_jobs(
                workspace,
                DiscoveryState(),
                (reviewed(candidate("REQ-1", record_id="same"), initial_hashes),),
                occurred_at="2026-09-11T12:01:00Z",
            )
            criteria, current_hashes = install_location_exclusion(workspace)
            invalid = reviewed(candidate("REQ-1", record_id="same"), current_hashes)
            invalid = replace(
                invalid,
                assessment=replace(
                    invalid.assessment,
                    profile_hash="0" * 64,
                    strengths=(EvidenceClaim("EV-MISSING", "Unsupported."),),
                ),
            )
            before = read_job(workspace, "JOB-000001")

            with self.assertRaises(AssessmentBatchError) as raised:
                deliver_reviewed_jobs(
                    workspace,
                    initial.state,
                    (invalid,),
                    occurred_at="2026-09-11T13:01:00Z",
                    criteria=criteria,
                )

            self.assertIn("unsupported_strength", raised.exception.codes)
            self.assertIn("stale_profile_hash", raised.exception.codes)
            self.assertEqual(read_job(workspace, "JOB-000001"), before)

    def test_hard_filter_reassesses_existing_role_without_rewinding_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            initial_hashes = approve_inputs(workspace)
            initial = deliver_reviewed_jobs(
                workspace,
                DiscoveryState(),
                (reviewed(candidate("REQ-1", record_id="same"), initial_hashes),),
                occurred_at="2026-09-11T12:01:00Z",
            )
            update_job_status(
                workspace,
                "JOB-000001",
                "interviewing",
                occurred_at="2026-09-11T12:02:00Z",
            )
            criteria, current_hashes = install_location_exclusion(workspace)

            outcome = deliver_reviewed_jobs(
                workspace,
                initial.state,
                (reviewed(candidate("REQ-1", record_id="same"), current_hashes),),
                occurred_at="2026-09-11T13:01:00Z",
                criteria=criteria,
            )

            record = read_job(workspace, "JOB-000001")
            self.assertEqual(record["disposition"], "non_match")
            self.assertEqual(record["status"], "interviewing")
            self.assertEqual(record["assessment_criteria_hash"], current_hashes[1])
            self.assertEqual(outcome.meaningful_change_job_ids, ("JOB-000001",))

    def test_late_assessment_cannot_overwrite_a_newer_assessment_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            hashes = approve_inputs(workspace)
            latest_candidate = candidate(
                "REQ-1",
                record_id="latest",
                content_hash="b" * 64,
                verified_at="2026-09-11T15:00:00Z",
            )
            latest = deliver_reviewed_jobs(
                workspace,
                DiscoveryState(),
                (reviewed(latest_candidate, hashes, disposition="worth_considering", fit="Latest fit"),),
                occurred_at="2026-09-11T15:01:00Z",
            )
            before = read_job(workspace, "JOB-000001")
            late_candidate = candidate(
                "REQ-1",
                record_id="late",
                content_hash="a" * 64,
                verified_at="2026-09-11T13:00:00Z",
            )

            outcome = deliver_reviewed_jobs(
                workspace,
                latest.state,
                (reviewed(late_candidate, hashes, disposition="non_match", fit="Stale fit"),),
                occurred_at="2026-09-11T13:01:00Z",
            )

            after = read_job(workspace, "JOB-000001")
            self.assertEqual(after["disposition"], "worth_considering")
            self.assertEqual(after["role_to_profile_fit"], "Latest fit")
            self.assertEqual(after["assessment_hash"], before["assessment_hash"])
            self.assertEqual(after["assessment_at"], "2026-09-11T15:01:00Z")
            self.assertEqual(outcome.meaningful_change_job_ids, ())

    def test_unchanged_assessment_advances_the_freshness_watermark(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            hashes = approve_inputs(workspace)
            original_candidate = candidate("REQ-1", record_id="same")
            assessment_a = reviewed(original_candidate, hashes, fit="Assessment A")
            first = deliver_reviewed_jobs(
                workspace,
                DiscoveryState(),
                (assessment_a,),
                occurred_at="2026-09-11T12:01:00Z",
            )
            refreshed_candidate = replace(
                original_candidate,
                verified_at="2026-09-11T15:00:00Z",
            )
            refreshed = deliver_reviewed_jobs(
                workspace,
                first.state,
                (reviewed(refreshed_candidate, hashes, fit="Assessment A"),),
                occurred_at="2026-09-11T15:01:00Z",
            )
            late = deliver_reviewed_jobs(
                workspace,
                refreshed.state,
                (reviewed(original_candidate, hashes, disposition="non_match", fit="Assessment B"),),
                occurred_at="2026-09-11T13:01:00Z",
            )

            record = read_job(workspace, "JOB-000001")
            self.assertEqual(record["role_to_profile_fit"], "Assessment A")
            self.assertEqual(record["assessment_at"], "2026-09-11T15:01:00Z")
            self.assertEqual(late.meaningful_change_job_ids, ())

    def test_novel_hard_rejection_does_not_require_semantic_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            criteria, _ = install_location_exclusion(workspace)
            item = ReviewedJob(
                candidate=replace(
                    candidate("REQ-1", record_id="hard-filtered"),
                    responsibilities=(),
                ),
                assessment=None,
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="",
            )

            outcome = deliver_reviewed_jobs(
                workspace,
                DiscoveryState(),
                (item,),
                occurred_at="2026-09-11T12:01:00Z",
                criteria=criteria,
            )

            self.assertEqual(outcome.created_job_ids, ())
            self.assertEqual(len(outcome.non_match_keys), 1)
            self.assertEqual(list(workspace.jobs.iterdir()), [])

    def test_invalid_later_assessment_rejects_entire_batch_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            hashes = approve_inputs(workspace)
            invalid = reviewed(candidate("REQ-2", record_id="invalid"), hashes)
            invalid = replace(
                invalid,
                candidate=replace(invalid.candidate, responsibilities=()),
                assessment=replace(invalid.assessment, strengths=(EvidenceClaim("EV-MISSING", "Unsupported."),)),
            )
            with self.assertRaises(AssessmentBatchError) as raised:
                deliver_reviewed_jobs(
                    workspace, DiscoveryState(),
                    (reviewed(candidate("REQ-1", record_id="valid"), hashes), invalid),
                    occurred_at="2026-09-11T12:05:00Z",
                )
            self.assertIn("responsibilities_missing", raised.exception.codes)
            self.assertIn("unsupported_strength", raised.exception.codes)
            self.assertEqual(list(workspace.jobs.iterdir()), [])
            self.assertEqual(json.loads((workspace.state / "next-job-id.json").read_text())["next_id"], 1)

    def test_stale_assessment_binding_is_rejected_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            current = approve_inputs(workspace)
            stale = reviewed(candidate("REQ-1", record_id="stale"), ("0" * 64, current[1]))
            with self.assertRaises(AssessmentBatchError) as raised:
                deliver_reviewed_jobs(
                    workspace, DiscoveryState(), (stale,), occurred_at="2026-09-11T12:05:00Z"
                )
            self.assertIn("stale_profile_hash", raised.exception.codes)
            self.assertEqual(list(workspace.jobs.iterdir()), [])

    def test_profile_change_after_batch_validation_aborts_before_job_mutation(self) -> None:
        import career_pipeline.discovery as discovery_module

        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            hashes = approve_inputs(workspace)
            original_load = discovery_module.load_indexes

            def change_profile(paths):
                result = original_load(paths)
                (paths.profile / "Career_Profile.md").write_text(
                    "# Changed after review\n\n- EV-010: Different evidence.\n",
                    encoding="utf-8",
                )
                return result

            with patch.object(discovery_module, "load_indexes", side_effect=change_profile):
                with self.assertRaises(AssessmentBatchError) as raised:
                    deliver_reviewed_jobs(
                        workspace, DiscoveryState(),
                        (reviewed(candidate("REQ-1", record_id="race"), hashes),),
                        occurred_at="2026-09-11T12:05:00Z",
                    )
            self.assertIn("profile_approval_stale", raised.exception.codes)
            self.assertEqual(list(workspace.jobs.iterdir()), [])
            self.assertEqual(json.loads((workspace.state / "next-job-id.json").read_text())["next_id"], 1)

    def test_cli_rejects_invalid_batch_with_codes_before_allocating_an_id(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            hashes = approve_inputs(workspace)
            valid = reviewed(candidate("REQ-1", record_id="valid"), hashes)
            invalid = reviewed(candidate("REQ-2", record_id="invalid"), hashes)
            invalid = replace(
                invalid,
                candidate=replace(invalid.candidate, responsibilities=()),
                assessment=replace(
                    invalid.assessment,
                    strengths=(EvidenceClaim("EV-MISSING", "Unsupported."),),
                ),
            )
            payload = Path(raw) / "reviewed.json"
            payload.write_text(
                json.dumps({"reviewed": [
                    {
                        "candidate": asdict(item.candidate),
                        "assessment": asdict(item.assessment),
                        "posting_markdown": item.posting_markdown,
                        "assessment_markdown": item.assessment_markdown,
                    }
                    for item in (valid, invalid)
                ]}),
                encoding="utf-8",
            )
            root = Path(__file__).resolve().parents[2]
            result = subprocess.run(
                [
                    sys.executable, str(root / "scripts" / "plan_discovery.py"),
                    "--workspace", str(workspace.root), "--reviewed", str(payload),
                    "--occurred-at", "2026-09-11T12:05:00Z",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("responsibilities_missing", result.stderr)
            self.assertIn("unsupported_strength", result.stderr)
            self.assertEqual(list(workspace.jobs.iterdir()), [])
            self.assertEqual(json.loads((workspace.state / "next-job-id.json").read_text())["next_id"], 1)

    def test_criteria_only_nonmatch_reassessment_updates_semantics_and_preserves_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            first_hashes = approve_inputs(workspace)
            first = deliver_reviewed_jobs(
                workspace, DiscoveryState(), (reviewed(candidate("REQ-1", record_id="same"), first_hashes),),
                occurred_at="2026-09-11T12:01:00Z",
            )
            update_job_status(workspace, "JOB-000001", "interviewing", occurred_at="2026-09-11T12:02:00Z")
            second_hashes = approve_inputs(workspace, criteria_text="Approved criteria v2")
            reassessed = deliver_reviewed_jobs(
                workspace, first.state,
                (reviewed(candidate("REQ-1", record_id="same"), second_hashes, disposition="non_match", fit="No longer aligned"),),
                occurred_at="2026-09-11T13:01:00Z",
            )
            record = read_job(workspace, "JOB-000001")
            self.assertEqual(reassessed.meaningful_change_job_ids, ("JOB-000001",))
            self.assertEqual(record["disposition"], "non_match")
            self.assertEqual(record["role_to_profile_fit"], "No longer aligned")
            self.assertEqual(record["assessment_criteria_hash"], second_hashes[1])
            self.assertEqual(record["status"], "interviewing")
            self.assertEqual(len(list(workspace.jobs.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
