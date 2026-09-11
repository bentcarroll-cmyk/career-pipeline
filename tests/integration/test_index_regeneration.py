from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from career_pipeline.evaluation import EvidenceClaim, JobAssessment
from career_pipeline.indexes import load_indexes, rebuild_indexes
from career_pipeline.job_store import create_job
from career_pipeline.sources.base import CandidateJob
from career_pipeline.workspace import create_workspace


def seed(workspace) -> None:
    create_job(
        workspace,
        CandidateJob(
            source="ashby",
            source_record_id="synthetic-record-9",
            requisition_id="SYN-709",
            employer="Example Studio",
            title="Business Operations Lead",
            responsibilities=("Lead fictional business operations.",),
            location="Remote",
            workplace_model="remote",
            travel=None,
            compensation_evidence=None,
            posting_url="https://jobs.example/postings/SYN-709",
            application_url="https://jobs.example/apply/SYN-709",
            team="Business Operations",
            posted_at=None,
            updated_at=None,
            deadline=None,
            verified_at="2026-09-11T17:00:00Z",
            verification_status="verified",
            raw_field_hash="9" * 64,
            uncertainties=("travel", "compensation"),
        ),
        JobAssessment(
            disposition="worth_considering",
            role_to_profile_fit="The fictional scope is relevant.",
            strengths=(EvidenceClaim("EV-009", "Led fictional operations."),),
            gaps=("One synthetic gap.",),
            uncertainties=(),
        ),
        posting_markdown="# Synthetic posting\n",
        assessment_markdown="# Synthetic assessment\n",
        occurred_at="2026-09-11T17:05:00Z",
    )


def canonical_bytes(workspace) -> dict[str, bytes]:
    return {
        path.relative_to(workspace.jobs).as_posix(): path.read_bytes()
        for path in workspace.jobs.rglob("*")
        if path.is_file()
    }


class IndexRegenerationTests(unittest.TestCase):
    def test_missing_and_corrupt_indexes_regenerate_without_canonical_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            seed(workspace)
            expected = rebuild_indexes(workspace)
            before = canonical_bytes(workspace)

            (workspace.indexes / "backlog.json").unlink()
            (workspace.indexes / "deduplication.json").write_text(
                "not-json", encoding="utf-8"
            )
            repaired = load_indexes(workspace)

            self.assertEqual(repaired, expected)
            self.assertEqual(canonical_bytes(workspace), before)
            self.assertEqual(
                json.loads((workspace.indexes / "backlog.json").read_text()),
                expected.backlog,
            )

    def test_unknown_job_id_forces_complete_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            seed(workspace)
            expected = rebuild_indexes(workspace)
            backlog_path = workspace.indexes / "backlog.json"
            tampered = json.loads(backlog_path.read_text(encoding="utf-8"))
            tampered["jobs"].append(
                {
                    "job_id": "JOB-999999",
                    "employer": "Unknown",
                    "title": "Unknown",
                    "disposition": "strong_match",
                    "status": "new",
                }
            )
            backlog_path.write_text(json.dumps(tampered), encoding="utf-8")

            repaired = load_indexes(workspace)

            self.assertEqual(repaired, expected)
            self.assertFalse(any(workspace.indexes.glob(".*.tmp")))


if __name__ == "__main__":
    unittest.main()
