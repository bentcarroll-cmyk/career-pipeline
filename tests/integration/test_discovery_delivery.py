import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from career_pipeline.checkpoints import DiscoveryState, load_discovery_state
from career_pipeline.discovery import ReviewedJob, deliver_reviewed_jobs
from career_pipeline.evaluation import EvidenceClaim, JobAssessment
from career_pipeline.job_store import read_job
from career_pipeline.reporting import discovery_report
from career_pipeline.sources.base import CandidateJob
from career_pipeline.workspace import create_workspace


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
        ),
        posting_markdown="# Synthetic posting\n",
        assessment_markdown="# Synthetic assessment\n",
    )


class DiscoveryDeliveryTests(unittest.TestCase):
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
