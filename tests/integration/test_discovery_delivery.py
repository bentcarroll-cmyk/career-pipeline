import tempfile
import unittest
from pathlib import Path

from career_pipeline.checkpoints import DiscoveryState
from career_pipeline.discovery import ReviewedJob, deliver_reviewed_jobs
from career_pipeline.evaluation import EvidenceClaim, JobAssessment
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
