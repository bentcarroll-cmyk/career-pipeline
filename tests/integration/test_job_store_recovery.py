import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from career_pipeline.evaluation import EvidenceClaim, JobAssessment
from career_pipeline.job_store import (
    JobStoreError,
    _commit_job_mutation_locked,
    create_job,
    read_job,
    update_job_status,
    workspace_lock,
)
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
    def test_invalid_pending_payload_is_rejected_before_journal_publish(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = create_job(
                workspace,
                candidate(),
                assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T12:00:00Z",
            )["job_id"]
            pending_path = (
                workspace.jobs / job_id / "working" / "pending-mutation.json"
            )

            with workspace_lock(workspace):
                current = read_job(workspace, job_id)
                invalid_event = {
                    "schema_version": 1,
                    "event_type": "status_changed",
                    "occurred_at": "2026-09-11T12:05:00Z",
                    "job_id": job_id,
                    "prior_status": "new",
                    "status": "unsupported_status",
                    "metadata": {},
                }
                with self.assertRaises(JobStoreError):
                    _commit_job_mutation_locked(
                        workspace,
                        job_id,
                        current,
                        invalid_event,
                    )

            self.assertFalse(pending_path.exists())
            updated = update_job_status(
                workspace,
                job_id,
                "applied",
                occurred_at="2026-09-11T12:10:00Z",
            )
            self.assertEqual(updated["status"], "applied")

    def test_preexisting_corrupt_journal_fails_closed_with_content_free_job_id(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = create_job(
                workspace,
                candidate(),
                assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T12:00:00Z",
            )["job_id"]
            pending_path = (
                workspace.jobs / job_id / "working" / "pending-mutation.json"
            )
            private_marker = "synthetic-private-posting-content"
            pending_path.write_text(
                '{"private": "' + private_marker + '",',
                encoding="utf-8",
            )

            with self.assertRaises(JobStoreError) as read_raised:
                read_job(workspace, job_id)
            self.assertIn(job_id, str(read_raised.exception))
            self.assertNotIn(private_marker, str(read_raised.exception))

            with self.assertRaises(JobStoreError) as raised:
                with workspace_lock(workspace):
                    pass

            diagnostic = str(raised.exception)
            self.assertIn(job_id, diagnostic)
            self.assertNotIn(private_marker, diagnostic)
            self.assertTrue(pending_path.is_file())

    def test_process_exit_releases_workspace_lock_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(
                Path(__file__).resolve().parents[2] / "src"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import os, sys\n"
                        "from pathlib import Path\n"
                        "from career_pipeline.job_store import workspace_lock\n"
                        "from career_pipeline.workspace import create_workspace\n"
                        "workspace = create_workspace(Path(sys.argv[1]))\n"
                        "with workspace_lock(workspace):\n"
                        "    os._exit(0)\n"
                    ),
                    str(workspace.root),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with workspace_lock(workspace):
                self.assertTrue((workspace.state / ".workspace.lock").is_file())

    def test_retry_recovers_event_and_snapshot_after_interrupted_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = create_job(
                workspace,
                candidate(),
                assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T12:00:00Z",
            )["job_id"]
            with patch(
                "career_pipeline.job_store.atomic_write_text",
                side_effect=OSError("synthetic interruption after journal"),
            ):
                with self.assertRaises(OSError):
                    update_job_status(
                        workspace,
                        job_id,
                        "applied",
                        occurred_at="2026-09-11T12:05:00Z",
                    )

            with self.assertRaises(JobStoreError):
                read_job(workspace, job_id)
            recovered = update_job_status(
                workspace,
                job_id,
                "applied",
                occurred_at="2026-09-11T12:05:00Z",
            )

            self.assertEqual(recovered["status"], "applied")
            events = (workspace.jobs / job_id / "events.jsonl").read_text().splitlines()
            self.assertEqual(len(events), 2)
            self.assertFalse(
                (workspace.jobs / job_id / "working" / "pending-mutation.json").exists()
            )

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
