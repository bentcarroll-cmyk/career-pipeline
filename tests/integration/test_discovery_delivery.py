import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from career_pipeline.checkpoints import DiscoveryState, load_discovery_state
from career_pipeline.atomic import atomic_write_json
from career_pipeline.criteria import (
    approve_workspace_criteria,
    ComparableThreshold,
    CriteriaError,
    CriteriaRule,
    NormalizedEvidence,
    SearchCriteria,
    criteria_to_mapping,
)
from career_pipeline.discovery import ReviewedJob, deliver_reviewed_jobs
from career_pipeline.evaluation import EvidenceClaim, JobAssessment
from career_pipeline.job_store import read_job
from career_pipeline.onboarding import OnboardingState, save_onboarding_state
from career_pipeline.reporting import discovery_report
from career_pipeline.sources.base import CandidateJob
from career_pipeline.workspace import create_workspace as _create_workspace


_PROFILE_TEXT = "# Synthetic career profile\n\n- EV-010: Synthetic operations evidence.\n"
_CRITERIA_TEXT = "# Approved synthetic criteria\n"
_PROFILE_HASH = hashlib.sha256(_PROFILE_TEXT.encode()).hexdigest()
_CRITERIA_HASH = hashlib.sha256(_CRITERIA_TEXT.encode()).hexdigest()


def create_workspace(root):
    workspace = _create_workspace(root)
    (workspace.profile / "Career_Profile.md").write_text(_PROFILE_TEXT, encoding="utf-8")
    (workspace.profile / "Search_Criteria.md").write_text(_CRITERIA_TEXT, encoding="utf-8")
    save_onboarding_state(
        workspace.state / "onboarding-state.json",
        OnboardingState(profile_hash=_PROFILE_HASH, criteria_hash=_CRITERIA_HASH),
    )
    return workspace


def candidate(number: int) -> CandidateJob:
    return CandidateJob(
        source="public-search",
        source_record_id=f"synthetic-{number}",
        requisition_id=f"SYN-{number}",
        employer="Example Cooperative",
        title=f"Operations Lead {number}",
        responsibilities=("Lead fictional operations.",),
        location="Example City",
        workplace_model="hybrid",
        travel=None,
        compensation_evidence=None,
        posting_url=f"https://jobs.example/postings/SYN-{number}",
        application_url=f"https://jobs.example/apply/SYN-{number}",
        team="Operations",
        posted_at=None,
        updated_at=None,
        deadline=None,
        verified_at="2026-09-11T18:00:00Z",
        verification_status="verified",
        raw_field_hash=f"{number:x}".rjust(64, "0"),
        uncertainties=("travel", "compensation"),
    )


def reviewed(number: int, disposition: str = "strong_match") -> ReviewedJob:
    strengths = (
        (EvidenceClaim("EV-010", "Led fictional operations."),)
        if disposition != "non_match"
        else ()
    )
    return ReviewedJob(
        candidate(number),
        JobAssessment(
            disposition=disposition,
            role_to_profile_fit="Synthetic responsibility comparison.",
            strengths=strengths,
            gaps=(),
            uncertainties=("Travel is not stated.",),
            profile_hash=_PROFILE_HASH,
            criteria_hash=_CRITERIA_HASH,
        ),
        posting_markdown="# Synthetic posting\n",
        assessment_markdown="# Synthetic assessment\n",
    )


def location_rule(*, accepted: str = "Remote") -> CriteriaRule:
    return CriteriaRule(
        criterion_id="location-approved",
        dimension="location",
        subject="job_location",
        classification="hard_exclusion",
        operator="one_of",
        reason_code="location_outside_approved_area",
        user_confirmed=True,
        values=(accepted,),
    )


def install_criteria(workspace, *rules: CriteriaRule) -> SearchCriteria:
    readable = workspace.profile / "Search_Criteria.md"
    readable.write_text("# Approved synthetic criteria\n", encoding="utf-8")
    readable_hash = hashlib.sha256(readable.read_bytes()).hexdigest()
    criteria = SearchCriteria(
        "Profile/Search_Criteria.md", readable_hash, rules
    )
    atomic_write_json(
        workspace.profile / "Search_Criteria.json",
        criteria_to_mapping(criteria),
    )
    save_onboarding_state(
        workspace.state / "onboarding-state.json",
        OnboardingState(profile_hash=_PROFILE_HASH, criteria_hash=readable_hash),
    )
    approve_workspace_criteria(
        workspace,
        expected_readable_sha256=readable_hash,
        expected_structured_sha256=criteria.structured_sha256,
    )
    return criteria


def travel_rule(maximum: str) -> CriteriaRule:
    return CriteriaRule(
        criterion_id="maximum-travel", dimension="travel",
        subject="travel_percentage", classification="hard_exclusion",
        operator="maximum", reason_code="travel_above_maximum",
        user_confirmed=True,
        threshold=ComparableThreshold(maximum, "percent"),
    )


def travel_evidence(number: int, value: str) -> NormalizedEvidence:
    return NormalizedEvidence(
        dimension="travel", subject="travel_percentage", status="known",
        value_type="number", provenance="source_receipt", certainty="verified",
        source="public-search", source_record_id=f"synthetic-{number}",
        source_field_hash=f"{number:x}".rjust(64, "0"), lower_bound=value,
        upper_bound=value, unit="percent",
    )


class DiscoveryDeliveryTests(unittest.TestCase):
    def test_default_rejection_creates_resolvable_immutable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            item = reviewed(790, "non_match")

            outcome = deliver_reviewed_jobs(
                workspace, DiscoveryState(), (item,),
                occurred_at="2026-09-11T12:00:00Z",
            )

            summary_text = outcome.run_evidence.read_text(encoding="utf-8")
            rejection = json.loads(summary_text)["rejections"][0]
            receipt_path = workspace.root / rejection["evidence_receipt_reference"]
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertTrue(receipt_path.is_file())
            self.assertEqual(receipt["identity"]["posting_url"], item.candidate.posting_url)
            self.assertEqual(receipt["identity"]["application_url"], item.candidate.application_url)
            self.assertEqual(receipt["responsibility_evidence"], ["Lead fictional operations."])
            self.assertEqual(
                receipt["rationale_summary"],
                "semantic_non_match:bounded_reason_summary",
            )
            self.assertNotIn(item.assessment.role_to_profile_fit, receipt_path.read_text(encoding="utf-8"))
            self.assertNotIn(item.assessment.role_to_profile_fit, summary_text)
            self.assertNotIn(item.posting_markdown, summary_text)
            self.assertNotIn("job_id", rejection)

    def test_approval_helper_records_only_current_explicit_criteria_approval(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            readable = workspace.profile / "Search_Criteria.md"
            readable.write_text("# Approved synthetic criteria\n", encoding="utf-8")
            readable_hash = hashlib.sha256(readable.read_bytes()).hexdigest()
            criteria = SearchCriteria(
                "Profile/Search_Criteria.md", readable_hash, (location_rule(),)
            )
            atomic_write_json(
                workspace.profile / "Search_Criteria.json",
                criteria_to_mapping(criteria),
            )
            save_onboarding_state(
                workspace.state / "onboarding-state.json",
                OnboardingState(criteria_hash=readable_hash),
            )

            approval = approve_workspace_criteria(
                workspace,
                expected_readable_sha256=readable_hash,
                expected_structured_sha256=criteria.structured_sha256,
            )

            self.assertEqual(
                approval,
                {
                    "schema_version": 1,
                    "readable_criteria_sha256": readable_hash,
                    "structured_criteria_sha256": criteria.structured_sha256,
                },
            )
            self.assertEqual(
                json.loads(
                    (workspace.state / "search-criteria-approval.json").read_text(
                        encoding="utf-8"
                    )
                ),
                approval,
            )

            readable.write_text("# Changed without renewed approval\n", encoding="utf-8")
            with self.assertRaises(CriteriaError):
                approve_workspace_criteria(
                    workspace,
                    expected_readable_sha256=readable_hash,
                    expected_structured_sha256=criteria.structured_sha256,
                )

    def test_approval_helper_cannot_overwrite_a_newer_reviewed_pair(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            older = install_criteria(workspace, location_rule())
            prior_receipt = (workspace.state / "search-criteria-approval.json").read_bytes()
            newer = install_criteria(workspace, location_rule(accepted="Example City"))
            newer_receipt = (workspace.state / "search-criteria-approval.json").read_bytes()
            self.assertNotEqual(older.structured_sha256, newer.structured_sha256)
            self.assertNotEqual(prior_receipt, newer_receipt)

            with self.assertRaises(CriteriaError):
                approve_workspace_criteria(
                    workspace,
                    expected_readable_sha256=older.readable_criteria_sha256,
                    expected_structured_sha256=older.structured_sha256,
                )

            self.assertEqual(
                (workspace.state / "search-criteria-approval.json").read_bytes(),
                newer_receipt,
            )

    def test_boolean_approval_schema_version_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            criteria = install_criteria(workspace, location_rule())
            atomic_write_json(
                workspace.state / "search-criteria-approval.json",
                {
                    "schema_version": True,
                    "readable_criteria_sha256": criteria.readable_criteria_sha256,
                    "structured_criteria_sha256": criteria.structured_sha256,
                },
            )
            with self.assertRaises(CriteriaError):
                deliver_reviewed_jobs(
                    workspace, DiscoveryState(), (reviewed(784),),
                    occurred_at="2026-09-11T07:00:00Z",
                )

    def test_approval_helper_rejects_symlinked_onboarding_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            criteria = install_criteria(workspace, location_rule())
            approval_path = workspace.state / "search-criteria-approval.json"
            prior_approval = approval_path.read_bytes()
            onboarding = workspace.state / "onboarding-state.json"
            external = Path(raw) / "onboarding-state.json"
            onboarding.rename(external)
            onboarding.symlink_to(external)

            with self.assertRaises(CriteriaError):
                approve_workspace_criteria(
                    workspace,
                    expected_readable_sha256=criteria.readable_criteria_sha256,
                    expected_structured_sha256=criteria.structured_sha256,
                )
            self.assertEqual(approval_path.read_bytes(), prior_approval)

    def test_private_prose_reason_code_is_rejected_without_a_run_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            item = reviewed(789, "non_match")
            item = replace(
                item,
                assessment=replace(
                    item.assessment,
                    reason_codes=("Private synthetic profile detail",),
                ),
            )
            with self.assertRaises(ValueError):
                deliver_reviewed_jobs(
                    workspace, DiscoveryState(), (item,),
                    occurred_at="2026-09-11T11:00:00Z",
                )
            self.assertEqual(list((workspace.runs / "discovery").iterdir()), [])

    def test_reason_codes_require_a_strict_tuple_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            item = reviewed(786, "non_match")
            item = replace(item, assessment=replace(item.assessment, reason_codes=["semantic_non_match"]))
            with self.assertRaises(ValueError):
                deliver_reviewed_jobs(
                    workspace, DiscoveryState(), (item,),
                    occurred_at="2026-09-11T09:00:00Z",
                )

    def test_duplicate_semantic_reason_codes_are_normalized_in_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            item = reviewed(772, "non_match")
            item = replace(
                item,
                assessment=replace(
                    item.assessment,
                    reason_codes=("semantic_non_match", "semantic_non_match"),
                ),
            )
            outcome = deliver_reviewed_jobs(
                workspace, DiscoveryState(), (item,),
                occurred_at="2026-09-11T00:30:00Z",
            )
            rejection = json.loads(outcome.run_evidence.read_text())[
                "rejections"
            ][0]
            self.assertEqual(rejection["reason_codes"], ["semantic_non_match"])
            self.assertEqual(rejection["reason_code_count"], 1)

    def test_changed_rules_or_normalized_evidence_change_decision_receipt_identity(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            first_criteria = install_criteria(workspace, travel_rule("25"))
            first_item = replace(
                reviewed(788),
                criteria_evidence=(travel_evidence(788, "80"),),
            )
            first = deliver_reviewed_jobs(
                workspace, DiscoveryState(), (first_item,),
                occurred_at="2026-09-11T10:00:00Z", criteria=first_criteria,
            )
            second_criteria = install_criteria(workspace, travel_rule("60"))
            second_item = replace(
                first_item, criteria_evidence=(travel_evidence(788, "70"),),
            )
            second = deliver_reviewed_jobs(
                workspace, first.state, (second_item,),
                occurred_at="2026-09-11T10:00:00Z", criteria=second_criteria,
            )
            first_rejection = json.loads(first.run_evidence.read_text())["rejections"][0]
            second_rejection = json.loads(second.run_evidence.read_text())["rejections"][0]
            self.assertNotEqual(first.run_evidence, second.run_evidence)
            self.assertNotEqual(first_rejection["criteria_hash"], second_rejection["criteria_hash"])
            self.assertNotEqual(first_rejection["assessment_hash"], second_rejection["assessment_hash"])
            self.assertNotEqual(first_rejection["evidence_receipt_reference"], second_rejection["evidence_receipt_reference"])

    def test_api_resolves_current_approved_workspace_criteria_when_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            install_criteria(workspace, location_rule())

            outcome = deliver_reviewed_jobs(
                workspace, DiscoveryState(), (replace(reviewed(793), assessment=None),),
                occurred_at="2026-09-11T15:00:00Z",
            )

            self.assertEqual(outcome.created_job_ids, ())
            self.assertEqual(list(workspace.jobs.iterdir()), [])

    def test_delivery_rejects_stale_supplied_criteria(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            stale = install_criteria(workspace, location_rule())
            install_criteria(workspace, location_rule(accepted="Example City"))

            with self.assertRaises(CriteriaError):
                deliver_reviewed_jobs(
                    workspace, DiscoveryState(), (reviewed(792),),
                    occurred_at="2026-09-11T14:00:00Z", criteria=stale,
                )

            self.assertEqual(list(workspace.jobs.iterdir()), [])

    def test_existing_structured_criteria_fail_closed_when_unapproved_or_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            approved = install_criteria(workspace, location_rule())
            cases = (
                (workspace.state / "search-criteria-approval.json", "missing approval"),
                (workspace.profile / "Search_Criteria.md", "missing readable criteria"),
                (workspace.profile / "Search_Criteria.json", "invalid structured criteria"),
            )
            for path, label in cases:
                install_criteria(workspace, location_rule())
                if "invalid" in label:
                    path.write_text("{invalid", encoding="utf-8")
                else:
                    path.unlink()
                with self.subTest(label=label):
                    with self.assertRaises(CriteriaError):
                        deliver_reviewed_jobs(
                            workspace, DiscoveryState(), (reviewed(791),),
                            occurred_at="2026-09-11T13:00:00Z", criteria=approved,
                        )
            self.assertEqual(list(workspace.jobs.iterdir()), [])

    def test_workspace_criteria_symlink_is_not_treated_as_current_approval(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            install_criteria(workspace, location_rule())
            structured = workspace.profile / "Search_Criteria.json"
            external = Path(raw) / "copied-criteria.json"
            external.write_bytes(structured.read_bytes())
            structured.unlink()
            structured.symlink_to(external)

            with self.assertRaises(CriteriaError):
                deliver_reviewed_jobs(
                    workspace, DiscoveryState(), (reviewed(785),),
                    occurred_at="2026-09-11T08:00:00Z",
                )

    def test_rejection_receipt_reference_rejects_prose_and_missing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            for reference in (
                "Private synthetic profile detail: compensation and personal history",
                "Runs/discovery/sources/receipt-" + "a" * 64 + ".json",
            ):
                item = replace(reviewed(794, "non_match"), source_receipt_reference=reference)
                with self.subTest(reference=reference):
                    with self.assertRaises(ValueError):
                        deliver_reviewed_jobs(
                            workspace, DiscoveryState(), (item,),
                            occurred_at="2026-09-11T16:00:00Z",
                        )

    def test_matching_hash_is_not_enough_for_an_upstream_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            item = reviewed(783, "non_match")
            malformed = {
                "identity": {
                    "source": item.candidate.source,
                    "source_record_id": item.candidate.source_record_id,
                },
                "source_snapshot": {"raw_field_hash": item.candidate.raw_field_hash},
            }
            encoded = json.dumps(
                malformed, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            reference = (
                "Runs/discovery/sources/receipt-"
                + hashlib.sha256(encoded).hexdigest()
                + ".json"
            )
            atomic_write_json(workspace.root / reference, malformed)

            with self.assertRaises(ValueError):
                deliver_reviewed_jobs(
                    workspace, DiscoveryState(),
                    (replace(item, source_receipt_reference=reference),),
                    occurred_at="2026-09-11T06:00:00Z",
                )

    def test_numeric_private_prose_is_not_persisted_by_api_or_cli(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace_root = Path(raw) / "Synthetic-Career"
            workspace = create_workspace(workspace_root)
            install_criteria(workspace, travel_rule("25"))
            private = "Private synthetic profile details copied into numeric evidence"
            item = replace(
                reviewed(782, "non_match"),
                criteria_evidence=(replace(travel_evidence(782, "80"), text_value=private),),
            )
            api = deliver_reviewed_jobs(
                workspace, DiscoveryState(), (item,),
                occurred_at="2026-09-11T05:00:00Z",
            )
            api_receipt = workspace.root / json.loads(
                api.run_evidence.read_text(encoding="utf-8")
            )["rejections"][0]["evidence_receipt_reference"]
            self.assertNotIn(private, api_receipt.read_text(encoding="utf-8"))

            payload = Path(raw) / "reviewed-private.json"
            payload.write_text(json.dumps({"reviewed": [{
                "candidate": asdict(item.candidate),
                "assessment": asdict(item.assessment),
                "posting_markdown": item.posting_markdown,
                "assessment_markdown": item.assessment_markdown,
                "criteria_evidence": [asdict(item.criteria_evidence[0])],
            }]}), encoding="utf-8")
            root = Path(__file__).resolve().parents[2]
            cli = subprocess.run([
                sys.executable, str(root / "scripts" / "plan_discovery.py"),
                "--workspace", str(workspace_root), "--reviewed", str(payload),
                "--occurred-at", "2026-09-11T05:30:00Z",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
            self.assertNotIn(
                private,
                (workspace_root / json.loads(cli.stdout)["run_evidence"]).read_text(
                    encoding="utf-8"
                ),
            )

    def test_four_hard_failures_retain_complete_decisions_without_aborting(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            rules = (
                location_rule(),
                CriteriaRule(
                    "workplace-approved", "workplace", "workplace_model",
                    "hard_exclusion", "one_of", "workplace_model_not_approved",
                    True, values=("remote",),
                ),
                CriteriaRule(
                    "role-approved", "role", "job_title", "hard_exclusion",
                    "one_of", "role_title_not_approved", True,
                    values=("Director",),
                ),
                travel_rule("25"),
            )
            install_criteria(workspace, *rules)
            item = replace(
                reviewed(781), assessment=None,
                criteria_evidence=(travel_evidence(781, "80"),),
            )
            qualifying = replace(
                reviewed(771),
                candidate=replace(
                    candidate(771), location="Remote", workplace_model="remote",
                    title="Director",
                ),
                criteria_evidence=(travel_evidence(771, "10"),),
            )

            outcome = deliver_reviewed_jobs(
                workspace, DiscoveryState(), (item, qualifying),
                occurred_at="2026-09-11T04:00:00Z",
            )

            run = json.loads(outcome.run_evidence.read_text(encoding="utf-8"))
            rejection = run["rejections"][0]
            receipt = json.loads(
                (workspace.root / rejection["evidence_receipt_reference"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(len(run["filter_outcomes"][0]["decisions"]), 4)
            self.assertEqual(len(receipt["filter_decisions"]), 4)
            self.assertEqual(rejection["reason_code_count"], 4)
            self.assertEqual(len(rejection["reason_codes"]), 3)
            self.assertEqual(outcome.created_job_ids, ("JOB-000001",))

    def test_receipt_directory_symlinks_are_rejected_for_generated_and_upstream_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            raw_path = Path(raw)
            for suffix, relative in (
                ("runs", "Runs"),
                ("discovery", "Runs/discovery"),
                ("sources", "Runs/discovery/sources"),
            ):
                workspace = create_workspace(raw_path / f"Synthetic-{suffix}")
                target = workspace.root / relative
                external_target = raw_path / f"external-{suffix}"
                if target.exists():
                    target.rename(external_target)
                else:
                    external_target.mkdir()
                target.symlink_to(external_target, target_is_directory=True)
                with self.subTest(relative=relative), self.assertRaises(ValueError):
                    deliver_reviewed_jobs(
                        workspace, DiscoveryState(), (reviewed(780, "non_match"),),
                        occurred_at="2026-09-11T03:00:00Z",
                    )

            workspace = create_workspace(raw_path / "Synthetic-Career")
            external = raw_path / "external-receipts"
            external.mkdir()
            sources = workspace.runs / "discovery" / "sources"
            sources.symlink_to(external, target_is_directory=True)
            with self.assertRaises(ValueError):
                deliver_reviewed_jobs(
                    workspace, DiscoveryState(), (reviewed(780, "non_match"),),
                    occurred_at="2026-09-11T03:00:00Z",
                )
            self.assertEqual(list(external.iterdir()), [])

            sources.unlink()
            first = deliver_reviewed_jobs(
                workspace, DiscoveryState(), (reviewed(779, "non_match"),),
                occurred_at="2026-09-11T02:00:00Z",
            )
            reference = json.loads(first.run_evidence.read_text())[
                "rejections"
            ][0]["evidence_receipt_reference"]
            sources.rename(external / "stored")
            sources.symlink_to(external / "stored", target_is_directory=True)
            with self.assertRaises(ValueError):
                deliver_reviewed_jobs(
                    workspace, first.state,
                    (replace(reviewed(779, "non_match"), source_receipt_reference=reference),),
                    occurred_at="2026-09-11T02:30:00Z",
                )

    def test_criteria_changes_in_either_direction_abort_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            for initial, replacement, number in (
                ("Example City", "Remote", 778),
                ("Remote", "Example City", 777),
            ):
                workspace = create_workspace(Path(raw) / f"Synthetic-{number}")
                install_criteria(workspace, location_rule(accepted=initial))
                original_load = __import__(
                    "career_pipeline.discovery", fromlist=["load_indexes"]
                ).load_indexes

                def change_criteria(paths, *, accepted=replacement):
                    result = original_load(paths)
                    readable = paths.profile / "Search_Criteria.md"
                    readable_hash = hashlib.sha256(readable.read_bytes()).hexdigest()
                    replacement_criteria = SearchCriteria(
                        "Profile/Search_Criteria.md", readable_hash,
                        (location_rule(accepted=accepted),),
                    )
                    atomic_write_json(
                        paths.profile / "Search_Criteria.json",
                        criteria_to_mapping(replacement_criteria),
                    )
                    save_onboarding_state(
                        paths.state / "onboarding-state.json",
                        OnboardingState(
                            profile_hash=_PROFILE_HASH,
                            criteria_hash=readable_hash,
                        ),
                    )
                    atomic_write_json(
                        paths.state / "search-criteria-approval.json",
                        {
                            "schema_version": 1,
                            "readable_criteria_sha256": readable_hash,
                            "structured_criteria_sha256": replacement_criteria.structured_sha256,
                        },
                    )
                    return result

                with self.subTest(initial=initial, replacement=replacement):
                    with patch(
                        "career_pipeline.discovery.load_indexes",
                        side_effect=change_criteria,
                    ), self.assertRaises(CriteriaError):
                        deliver_reviewed_jobs(
                            workspace, DiscoveryState(),
                            (reviewed(number),),
                            occurred_at="2026-09-11T01:00:00Z",
                        )
                    self.assertEqual(list(workspace.jobs.iterdir()), [])
                    self.assertEqual(
                        list((workspace.runs / "discovery").glob("run-*.json")), []
                    )

    def test_discovery_cli_loads_hash_bound_structured_criteria(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace_root = Path(raw) / "Synthetic-Career"
            workspace = create_workspace(workspace_root)
            install_criteria(workspace, location_rule())
            payload_path = Path(raw) / "reviewed.json"
            item = reviewed(795)
            payload_path.write_text(
                json.dumps({"reviewed": [{
                    "candidate": asdict(item.candidate),
                    "assessment": asdict(item.assessment),
                    "posting_markdown": item.posting_markdown,
                    "assessment_markdown": item.assessment_markdown,
                }]}),
                encoding="utf-8",
            )
            root = Path(__file__).resolve().parents[2]

            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts" / "plan_discovery.py"),
                    "--workspace",
                    str(workspace_root),
                    "--reviewed",
                    str(payload_path),
                    "--occurred-at",
                    "2026-09-11T18:05:00Z",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = json.loads(result.stdout)
            evidence = json.loads(
                (workspace_root / output["run_evidence"]).read_text(encoding="utf-8")
            )
            self.assertEqual(output["created_job_ids"], [])
            self.assertEqual(list(workspace.jobs.iterdir()), [])
            self.assertEqual(
                evidence["rejections"][0]["decision"], "hard_filter_rejection"
            )

    def test_discovery_cli_keeps_conflicting_or_malformed_override_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace_root = Path(raw) / "Synthetic-Career"
            workspace = create_workspace(workspace_root)
            install_criteria(workspace, location_rule())
            item = replace(reviewed(787), candidate=replace(candidate(787), location="Remote"))
            conflicting = {
                "dimension": "location", "subject": "job_location", "status": "known",
                "value_type": "text", "provenance": "source_receipt", "certainty": "verified",
                "source": item.candidate.source,
                "source_record_id": item.candidate.source_record_id,
                "source_field_hash": item.candidate.raw_field_hash,
                "text_value": "Chicago",
            }
            payload = Path(raw) / "reviewed.json"
            payload.write_text(json.dumps({"reviewed": [{
                "candidate": asdict(item.candidate),
                "assessment": asdict(item.assessment),
                "posting_markdown": item.posting_markdown,
                "assessment_markdown": item.assessment_markdown,
                "criteria_evidence": [conflicting, {"dimension": "location", "status": "unknown"}],
            }]}), encoding="utf-8")
            root = Path(__file__).resolve().parents[2]
            result = subprocess.run([
                sys.executable, str(root / "scripts" / "plan_discovery.py"),
                "--workspace", str(workspace_root), "--reviewed", str(payload),
                "--occurred-at", "2026-09-11T18:05:00Z",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["created_job_ids"], ["JOB-000001"])

    def test_discovery_cli_normalizes_blank_unknown_and_group_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace_root = Path(raw) / "Synthetic-Career"
            workspace = create_workspace(workspace_root)
            install_criteria(workspace, location_rule())
            reviewed_items = []
            for number, variant in zip(
                (776, 775, 774),
                (
                    {"status": "unknown"},
                    {"status": "known", "text_value": "Unknown"},
                    {"status": "known", "text_value": "   "},
                ),
            ):
                item = replace(
                    reviewed(number),
                    candidate=replace(candidate(number), location="Chicago"),
                )
                normalized = {
                    "dimension": "location", "subject": "job_location",
                    "value_type": "text", "provenance": "source_receipt",
                    "certainty": "verified", "source": item.candidate.source,
                    "source_record_id": item.candidate.source_record_id,
                    "source_field_hash": item.candidate.raw_field_hash,
                    **variant,
                }
                reviewed_items.append({
                    "candidate": asdict(item.candidate),
                    "assessment": asdict(item.assessment),
                    "posting_markdown": item.posting_markdown,
                    "assessment_markdown": item.assessment_markdown,
                    "criteria_evidence": [normalized],
                })
            conflict_item = replace(
                reviewed(773), candidate=replace(candidate(773), location="Chicago")
            )
            conflict_base = {
                "dimension": "location", "subject": "job_location",
                "status": "known", "value_type": "text",
                "provenance": "source_receipt", "certainty": "verified",
                "source": conflict_item.candidate.source,
                "source_record_id": conflict_item.candidate.source_record_id,
                "source_field_hash": conflict_item.candidate.raw_field_hash,
            }
            reviewed_items.append({
                "candidate": asdict(conflict_item.candidate),
                "assessment": asdict(conflict_item.assessment),
                "posting_markdown": conflict_item.posting_markdown,
                "assessment_markdown": conflict_item.assessment_markdown,
                "criteria_evidence": [
                    {**conflict_base, "text_value": "Remote"},
                    {**conflict_base, "text_value": "Boston"},
                ],
            })
            payload = Path(raw) / "reviewed-unknowns.json"
            payload.write_text(
                json.dumps({"reviewed": reviewed_items}), encoding="utf-8"
            )
            root = Path(__file__).resolve().parents[2]
            result = subprocess.run([
                sys.executable, str(root / "scripts" / "plan_discovery.py"),
                "--workspace", str(workspace_root), "--reviewed", str(payload),
                "--occurred-at", "2026-09-11T18:05:00Z",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len(json.loads(result.stdout)["created_job_ids"]), 4)

    def test_hard_filter_rejection_writes_compact_audit_without_allocating_id(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            criteria = install_criteria(workspace, location_rule())
            item = replace(
                reviewed(797),
                assessment=None,
            )

            outcome = deliver_reviewed_jobs(
                workspace,
                DiscoveryState(),
                (item,),
                occurred_at="2026-09-11T18:00:00Z",
                criteria=criteria,
            )

            evidence_text = outcome.run_evidence.read_text(encoding="utf-8")
            evidence = json.loads(evidence_text)
            self.assertEqual(outcome.created_job_ids, ())
            self.assertEqual(list(workspace.jobs.iterdir()), [])
            self.assertEqual(len(evidence["rejections"]), 1)
            rejection = evidence["rejections"][0]
            self.assertEqual(rejection["decision"], "hard_filter_rejection")
            self.assertEqual(rejection["filter_result"], "confirmed_mismatch")
            self.assertEqual(
                rejection["reason_codes"], ["location_outside_approved_area"]
            )
            self.assertEqual(
                rejection["source_receipt_reference"],
                rejection["evidence_receipt_reference"],
            )
            self.assertEqual(rejection["criteria_hash"], criteria.structured_sha256)
            self.assertRegex(rejection["assessment_hash"], r"^[0-9a-f]{64}$")
            self.assertNotIn("job_id", rejection)
            self.assertNotIn(item.posting_markdown, evidence_text)
            self.assertNotIn(item.assessment_markdown, evidence_text)

    def test_semantic_non_match_can_be_explicitly_promoted_on_later_review(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            non_match = replace(
                reviewed(796, "non_match"),
                assessment=replace(
                    reviewed(796, "non_match").assessment,
                    reason_codes=("responsibilities_do_not_align",),
                ),
            )

            rejected = deliver_reviewed_jobs(
                workspace,
                DiscoveryState(),
                (non_match,),
                occurred_at="2026-09-11T17:00:00Z",
            )
            promoted = deliver_reviewed_jobs(
                workspace,
                rejected.state,
                (reviewed(796),),
                occurred_at="2026-09-11T18:00:00Z",
            )

            rejection = json.loads(rejected.run_evidence.read_text())["rejections"][0]
            self.assertEqual(rejection["decision"], "semantic_non_match")
            self.assertEqual(
                rejection["reason_codes"], ["responsibilities_do_not_align"]
            )
            self.assertNotIn("job_id", rejection)
            self.assertEqual(rejected.created_job_ids, ())
            self.assertEqual(promoted.created_job_ids, ("JOB-000001",))

    def test_out_of_order_reverification_cannot_replace_newer_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            first = deliver_reviewed_jobs(
                workspace,
                DiscoveryState(),
                (reviewed(798),),
                occurred_at="2026-09-11T18:00:00Z",
            )
            newer_review = reviewed(798)
            newer_review = replace(
                newer_review,
                candidate=replace(
                    newer_review.candidate,
                    deadline="2026-10-15",
                    verified_at="2026-09-11T20:00:00Z",
                    raw_field_hash="e" * 64,
                ),
                posting_markdown="# Newer synthetic posting\n",
            )
            newer = deliver_reviewed_jobs(
                workspace,
                first.state,
                (newer_review,),
                occurred_at="2026-09-11T20:05:00Z",
            )
            stale_review = replace(
                newer_review,
                candidate=replace(
                    newer_review.candidate,
                    deadline="2026-09-30",
                    verified_at="2026-09-11T19:00:00Z",
                    raw_field_hash="d" * 64,
                ),
                posting_markdown="# Stale synthetic posting\n",
            )

            stale = deliver_reviewed_jobs(
                workspace,
                newer.state,
                (stale_review,),
                occurred_at="2026-09-11T19:05:00Z",
            )

            canonical = read_job(workspace, "JOB-000001")
            self.assertEqual(stale.meaningful_change_job_ids, ())
            self.assertEqual(canonical["deadline"], "2026-10-15")
            self.assertEqual(canonical["verified_at"], "2026-09-11T20:00:00Z")
            self.assertEqual(canonical["reverified_at"], "2026-09-11T20:05:00Z")
            self.assertEqual(
                (workspace.jobs / "JOB-000001" / "posting.md").read_text(),
                "# Newer synthetic posting\n",
            )

    def test_unchanged_success_refreshes_reverification_without_change_alert(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            first = deliver_reviewed_jobs(
                workspace,
                DiscoveryState(),
                (reviewed(799),),
                occurred_at="2026-09-11T18:00:00Z",
            )

            second = deliver_reviewed_jobs(
                workspace,
                first.state,
                (reviewed(799),),
                occurred_at="2026-09-11T19:00:00Z",
            )

            self.assertEqual(second.meaningful_change_job_ids, ())
            self.assertEqual(
                read_job(workspace, "JOB-000001")["reverified_at"],
                "2026-09-11T19:00:00Z",
            )

    def test_discovery_cli_persists_source_checkpoint_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace_root = Path(raw) / "Synthetic-Career"
            create_workspace(workspace_root)
            payload_path = Path(raw) / "synthetic-reviewed.json"
            item = reviewed(800)
            payload_path.write_text(
                json.dumps(
                    {
                        "reviewed": [
                            {
                                "candidate": asdict(item.candidate),
                                "assessment": asdict(item.assessment),
                                "posting_markdown": item.posting_markdown,
                                "assessment_markdown": item.assessment_markdown,
                            }
                        ],
                        "source_results": {
                            "public-search": {
                                "success": True,
                                "completed_at": "2026-09-11T18:05:00Z",
                                "seen_records": ["synthetic-800"],
                                "cursor": "synthetic-next",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            root = Path(__file__).resolve().parents[2]
            command = [
                sys.executable,
                str(root / "scripts" / "plan_discovery.py"),
                "--workspace",
                str(workspace_root),
                "--reviewed",
                str(payload_path),
                "--occurred-at",
                "2026-09-11T18:05:00Z",
            ]

            first = subprocess.run(command, check=False, capture_output=True, text=True)
            second = subprocess.run(command, check=False, capture_output=True, text=True)

            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            state = load_discovery_state(
                workspace_root / "State" / "discovery-state.json"
            )
            self.assertEqual(state.sources["public-search"].cursor, "synthetic-next")
            self.assertEqual(
                state.canonical_jobs["req:example cooperative:syn-800"],
                "JOB-000001",
            )
            self.assertEqual(len(list((workspace_root / "Jobs").iterdir())), 1)

    def test_discovery_cli_rejects_missing_enabled_source_lane(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace_root = Path(raw) / "Synthetic-Career"
            workspace = create_workspace(workspace_root)
            atomic_write_json(
                workspace.state / "config.json",
                {"enabled_sources": ["public_ats", "indeed"]},
            )
            item = reviewed(804)
            payload_path = Path(raw) / "incomplete-source-coverage.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "reviewed": [
                            {
                                "candidate": asdict(item.candidate),
                                "assessment": asdict(item.assessment),
                                "posting_markdown": item.posting_markdown,
                                "assessment_markdown": item.assessment_markdown,
                            }
                        ],
                        "source_results": {
                            "indeed": {
                                "success": True,
                                "completed_at": "2026-09-11T18:05:00Z",
                                "seen_records": ["synthetic-804"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            root = Path(__file__).resolve().parents[2]

            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts" / "plan_discovery.py"),
                    "--workspace",
                    str(workspace_root),
                    "--reviewed",
                    str(payload_path),
                    "--occurred-at",
                    "2026-09-11T18:05:00Z",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            error = json.loads(result.stderr)
            self.assertEqual(error["error"], "source_coverage_incomplete")
            self.assertEqual(error["missing_enabled_sources"], ["public_ats"])
            self.assertEqual(list(workspace.jobs.iterdir()), [])
            self.assertEqual(
                list((workspace.runs / "discovery").glob("run-*.json")), []
            )

    def test_qualifying_jobs_are_local_and_non_matches_stay_in_run_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")

            outcome = deliver_reviewed_jobs(
                workspace,
                DiscoveryState(),
                (reviewed(801), reviewed(802, "non_match")),
                occurred_at="2026-09-11T18:05:00Z",
            )

            self.assertEqual(outcome.created_job_ids, ("JOB-000001",))
            self.assertEqual(len(outcome.non_match_keys), 1)
            self.assertEqual(list(workspace.jobs.iterdir())[0].name, "JOB-000001")
            self.assertEqual(
                outcome.state.canonical_jobs["req:example cooperative:syn-801"],
                "JOB-000001",
            )
            self.assertTrue(outcome.run_evidence.is_file())
            self.assertNotIn("SYN-802", outcome.state.canonical_jobs.values())

    def test_second_delivery_rechecks_canonical_folders_and_does_not_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            first = deliver_reviewed_jobs(
                workspace,
                DiscoveryState(),
                (reviewed(803),),
                occurred_at="2026-09-11T18:05:00Z",
            )
            second = deliver_reviewed_jobs(
                workspace,
                first.state,
                (reviewed(803),),
                occurred_at="2026-09-11T18:10:00Z",
            )

            self.assertEqual(second.created_job_ids, ())
            self.assertEqual(len(second.duplicate_keys), 1)
            self.assertEqual(len(list(workspace.jobs.iterdir())), 1)

    def test_changed_same_source_duplicate_reverifies_canonical_job(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            first = deliver_reviewed_jobs(
                workspace,
                DiscoveryState(),
                (reviewed(804),),
                occurred_at="2026-09-11T18:05:00Z",
            )
            changed_review = reviewed(804)
            changed_review = replace(
                changed_review,
                candidate=replace(
                    changed_review.candidate,
                    deadline="2026-10-01",
                    verified_at="2026-09-11T19:00:00Z",
                    raw_field_hash="f" * 64,
                ),
                posting_markdown="# Updated synthetic posting\n",
            )

            second = deliver_reviewed_jobs(
                workspace,
                first.state,
                (changed_review,),
                occurred_at="2026-09-11T19:05:00Z",
            )

            self.assertEqual(second.meaningful_change_job_ids, ("JOB-000001",))
            updated = read_job(workspace, "JOB-000001")
            self.assertEqual(updated["deadline"], "2026-10-01")
            self.assertEqual(updated["reverified_at"], "2026-09-11T19:05:00Z")
            self.assertEqual(
                (workspace.jobs / "JOB-000001" / "posting.md").read_text(),
                "# Updated synthetic posting\n",
            )
            events = (
                workspace.jobs / "JOB-000001" / "events.jsonl"
            ).read_text().splitlines()
            self.assertEqual(json.loads(events[-1])["event_type"], "job_reverified")

    def test_higher_priority_cross_source_evidence_updates_canonical_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            first = deliver_reviewed_jobs(
                workspace,
                DiscoveryState(),
                (reviewed(805),),
                occurred_at="2026-09-11T18:05:00Z",
            )
            ats_review = reviewed(805)
            ats_review = replace(
                ats_review,
                candidate=replace(
                    ats_review.candidate,
                    source="greenhouse",
                    source_record_id="synthetic-greenhouse-805",
                    travel="Up to 10 percent",
                    verified_at="2026-09-11T19:00:00Z",
                    raw_field_hash="c" * 64,
                ),
                posting_markdown="# Synthetic ATS posting\n",
            )

            second = deliver_reviewed_jobs(
                workspace,
                first.state,
                (ats_review,),
                occurred_at="2026-09-11T19:05:00Z",
            )

            updated = read_job(workspace, "JOB-000001")
            self.assertEqual(second.meaningful_change_job_ids, ("JOB-000001",))
            self.assertEqual(updated["source"], "greenhouse")
            self.assertEqual(updated["travel"], "Up to 10 percent")

    def test_quiet_report_suppresses_unchanged_failures(self) -> None:
        self.assertIsNone(discovery_report((), (), (), ()))
        self.assertIsNone(
            discovery_report((), (), ("indeed_unavailable",), ("indeed_unavailable",))
        )
        report = discovery_report(
            ("JOB-000001",), (), ("browser_expired",), ("indeed_unavailable",)
        )
        self.assertIn("JOB-000001", report)
        self.assertIn("browser_expired", report)


if __name__ == "__main__":
    unittest.main()
