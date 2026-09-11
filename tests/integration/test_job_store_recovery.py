import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from career_pipeline.evaluation import EvidenceClaim, JobAssessment
from career_pipeline.job_store import JobStoreError, create_job, read_job
from career_pipeline.sources.base import CandidateJob
from career_pipeline.workspace import create_workspace


def candidate() -> CandidateJob:
    return CandidateJob(
        source="greenhouse",
        source_record_id="synthetic-record-2",
        requisition_id="SYN-602",
        employer="Example Research Group",
        title="Strategy Lead",
        responsibilities=("Lead a fictional strategy process.",),
        location=None,
        workplace_model=None,
        travel=None,
        compensation_evidence=None,
        posting_url="https://jobs.example/postings/SYN-602",
        application_url="https://jobs.example/apply/SYN-602",
        team="Strategy",
        posted_at=None,
        updated_at=None,
        deadline=None,
        verified_at="2026-09-11T14:00:00Z",
        verification_status="verified",
        raw_field_hash="b" * 64,
        uncertainties=("location", "workplace_model", "travel", "compensation"),
    )


def assessment() -> JobAssessment:
    return JobAssessment(
        disposition="worth_considering",
        role_to_profile_fit="The fictional scope is relevant.",
        strengths=(EvidenceClaim("EV-002", "Led fictional strategy work."),),
        gaps=("Location needs confirmation.",),
        uncertainties=("Compensation is not stated.",),
    )


class JobStoreRecoveryTests(unittest.TestCase):
    def test_failed_creation_consumes_id_and_removes_temporary_folder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            with patch(
                "career_pipeline.job_store._write_job_files",
                side_effect=OSError("synthetic interruption"),
            ):
                with self.assertRaises(OSError):
                    create_job(
                        workspace,
                        candidate(),
                        assessment(),
                        posting_markdown="# Synthetic posting\n",
                        assessment_markdown="# Synthetic assessment\n",
                        occurred_at="2026-09-11T14:05:00Z",
                    )

            self.assertEqual(list(workspace.jobs.iterdir()), [])
            counter = json.loads(
                (workspace.state / "next-job-id.json").read_text(encoding="utf-8")
            )
            self.assertEqual(counter["next_id"], 2)
            created = create_job(
                workspace,
                candidate(),
                assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T14:10:00Z",
            )
            self.assertEqual(created["job_id"], "JOB-000002")

    def test_corrupt_or_mismatched_canonical_record_fails_readback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            create_job(
                workspace,
                candidate(),
                assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T14:05:00Z",
            )
            job_path = workspace.jobs / "JOB-000001" / "job.json"
            value = json.loads(job_path.read_text(encoding="utf-8"))
            value["job_id"] = "JOB-000999"
            job_path.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaises(JobStoreError):
                read_job(workspace, "JOB-000001")


if __name__ == "__main__":
    unittest.main()
