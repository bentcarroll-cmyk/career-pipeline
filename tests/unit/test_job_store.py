import json
import tempfile
import unittest
from pathlib import Path

from career_pipeline.evaluation import EvidenceClaim, JobAssessment
from career_pipeline.job_store import (
    JobStoreError,
    WorkspaceLockedError,
    allocate_job_id,
    create_job,
    read_job,
    update_job_status,
    workspace_lock,
)
from career_pipeline.sources.base import CandidateJob
from career_pipeline.workspace import create_workspace


def synthetic_candidate() -> CandidateJob:
    return CandidateJob(
        source="public-search",
        source_record_id="synthetic-record-1",
        requisition_id="SYN-601",
        employer="Example Cooperative",
        title="Director of Operations",
        responsibilities=("Lead a fictional operating cadence.",),
        location="Example City",
        workplace_model="hybrid",
        travel=None,
        compensation_evidence=None,
        posting_url="https://jobs.example/postings/SYN-601",
        application_url="https://jobs.example/apply/SYN-601",
        team="Operations",
        posted_at="2026-09-10T12:00:00Z",
        updated_at=None,
        deadline=None,
        verified_at="2026-09-11T12:00:00Z",
        verification_status="verified",
        raw_field_hash="a" * 64,
        uncertainties=("travel", "compensation"),
    )


def synthetic_assessment() -> JobAssessment:
    return JobAssessment(
        disposition="strong_match",
        role_to_profile_fit="Synthetic evidence supports the core work.",
        strengths=(EvidenceClaim("EV-001", "Built a fictional cadence."),),
        gaps=("Industry depth needs confirmation.",),
        uncertainties=("Travel is not stated.",),
    )


class JobStoreTests(unittest.TestCase):
    def test_lock_is_exclusive_and_released(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")

            with workspace_lock(workspace):
                with self.assertRaises(WorkspaceLockedError):
                    with workspace_lock(workspace):
                        pass

            with workspace_lock(workspace):
                self.assertTrue((workspace.state / ".workspace.lock").exists())
            self.assertFalse((workspace.state / ".workspace.lock").exists())

    def test_ids_are_six_digit_monotonic_and_never_reused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")

            self.assertEqual(allocate_job_id(workspace), "JOB-000001")
            self.assertEqual(allocate_job_id(workspace), "JOB-000002")
            counter = json.loads(
                (workspace.state / "next-job-id.json").read_text(encoding="utf-8")
            )
            self.assertEqual(counter["next_id"], 3)

    def test_create_reads_back_complete_canonical_folder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            record = create_job(
                workspace,
                synthetic_candidate(),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T12:05:00Z",
            )

            self.assertEqual(record["job_id"], "JOB-000001")
            job_dir = workspace.jobs / "JOB-000001"
            self.assertEqual(
                {path.name for path in job_dir.iterdir()},
                {"job.json", "posting.md", "assessment.md", "events.jsonl", "working"},
            )
            self.assertEqual(read_job(workspace, "JOB-000001"), record)
            self.assertEqual(record["paths"]["posting"], "Jobs/JOB-000001/posting.md")
            event = json.loads((job_dir / "events.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(event["event_type"], "job_created")

    def test_status_update_is_atomic_append_only_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            create_job(
                workspace,
                synthetic_candidate(),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T12:05:00Z",
            )

            changed = update_job_status(
                workspace,
                "JOB-000001",
                "not_pursuing",
                occurred_at="2026-09-11T13:00:00Z",
                metadata={"reason_code": "synthetic_user_decision"},
            )
            repeated = update_job_status(
                workspace,
                "JOB-000001",
                "not_pursuing",
                occurred_at="2026-09-11T13:05:00Z",
            )

            self.assertEqual(changed, repeated)
            self.assertTrue((workspace.jobs / "JOB-000001").is_dir())
            events = (workspace.jobs / "JOB-000001" / "events.jsonl").read_text().splitlines()
            self.assertEqual(len(events), 2)
            self.assertEqual(json.loads(events[-1])["prior_status"], "new")

    def test_invalid_status_and_identifier_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            with self.assertRaises(JobStoreError):
                read_job(workspace, "../JOB-000001")
            with self.assertRaises(JobStoreError):
                update_job_status(
                    workspace,
                    "JOB-000001",
                    "deleted",
                    occurred_at="2026-09-11T13:00:00Z",
                )


if __name__ == "__main__":
    unittest.main()
