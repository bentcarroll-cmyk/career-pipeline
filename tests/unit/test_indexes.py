from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from career_pipeline.evaluation import EvidenceClaim, JobAssessment
from career_pipeline.indexes import load_indexes, rebuild_indexes
from career_pipeline.job_store import create_job, update_job_status
from career_pipeline.sources.base import CandidateJob
from career_pipeline.workspace import create_workspace


def candidate(number: int, *, requisition_id: str | None = None) -> CandidateJob:
    return CandidateJob(
        source="public-search",
        source_record_id=f"synthetic-record-{number}",
        requisition_id=requisition_id,
        employer="Example Cooperative",
        title=f"Operations Lead {number}",
        responsibilities=("Lead a fictional operating cadence.",),
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
        verified_at="2026-09-11T15:00:00Z",
        verification_status="verified",
        raw_field_hash=f"{number:x}".rjust(64, "0"),
        uncertainties=("travel", "compensation"),
    )


def assessment() -> JobAssessment:
    return JobAssessment(
        disposition="strong_match",
        role_to_profile_fit="Synthetic evidence supports the role.",
        strengths=(EvidenceClaim("EV-003", "Led fictional operations."),),
        gaps=(),
        uncertainties=("Travel is not stated.",),
    )


def create_synthetic_job(workspace, number: int, *, requisition_id: str | None = None):
    return create_job(
        workspace,
        candidate(number, requisition_id=requisition_id),
        assessment(),
        posting_markdown="# Synthetic posting\n",
        assessment_markdown="# Synthetic assessment\n",
        occurred_at="2026-09-11T15:05:00Z",
    )


class IndexTests(unittest.TestCase):
    def test_rebuild_creates_stable_backlog_and_both_identity_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            create_synthetic_job(workspace, 1, requisition_id="SYN-701")
            create_synthetic_job(workspace, 2)

            indexes = rebuild_indexes(workspace)

            self.assertEqual(
                [record["job_id"] for record in indexes.backlog["jobs"]],
                ["JOB-000001", "JOB-000002"],
            )
            identities = indexes.deduplication["identities"]
            self.assertIn("req:example cooperative:syn-701", identities)
            self.assertEqual(len([key for key in identities if key.startswith("fp:")]), 2)
            self.assertTrue((workspace.indexes / "backlog.json").is_file())
            self.assertTrue((workspace.indexes / "deduplication.json").is_file())

    def test_closed_and_not_pursuing_jobs_remain_in_duplicate_index(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            create_synthetic_job(workspace, 1, requisition_id="SYN-702")
            update_job_status(
                workspace,
                "JOB-000001",
                "closed",
                occurred_at="2026-09-11T16:00:00Z",
            )

            indexes = rebuild_indexes(workspace)

            self.assertEqual(
                indexes.deduplication["identities"]["req:example cooperative:syn-702"],
                ["JOB-000001"],
            )
            self.assertEqual(indexes.backlog["jobs"][0]["status"], "closed")

    def test_stale_index_is_repaired_after_canonical_change(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            create_synthetic_job(workspace, 1)
            before = rebuild_indexes(workspace)
            update_job_status(
                workspace,
                "JOB-000001",
                "not_pursuing",
                occurred_at="2026-09-11T16:00:00Z",
            )

            after = load_indexes(workspace)

            self.assertNotEqual(before.backlog["source_hash"], after.backlog["source_hash"])
            self.assertEqual(after.backlog["jobs"][0]["status"], "not_pursuing")


if __name__ == "__main__":
    unittest.main()
