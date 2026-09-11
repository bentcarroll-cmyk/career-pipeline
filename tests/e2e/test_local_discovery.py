import json
import tempfile
import unittest
from pathlib import Path

from career_pipeline.checkpoints import DiscoveryState
from career_pipeline.discovery import ReviewedJob, deliver_reviewed_jobs
from career_pipeline.evaluation import EvidenceClaim, JobAssessment
from career_pipeline.indexes import load_indexes
from career_pipeline.sources.base import SourceSnapshot
from career_pipeline.sources.greenhouse import normalize
from career_pipeline.workspace import create_workspace


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "synthetic"
    / "postings"
    / "greenhouse.json"
)


class LocalDiscoveryTests(unittest.TestCase):
    def test_normalized_role_becomes_readable_local_backlog(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            source = json.loads(FIXTURE.read_text(encoding="utf-8"))
            job = normalize(
                SourceSnapshot("greenhouse", "2026-09-11T19:00:00Z", source)
            )[0]
            reviewed = ReviewedJob(
                job,
                JobAssessment(
                    disposition="strong_match",
                    role_to_profile_fit="Synthetic evidence aligns to the responsibilities.",
                    strengths=(EvidenceClaim("EV-011", "Led fictional operations."),),
                    gaps=(),
                    uncertainties=("Travel is not stated.",),
                ),
                posting_markdown="# Synthetic normalized posting\n",
                assessment_markdown="# Synthetic evidence-backed assessment\n",
            )

            outcome = deliver_reviewed_jobs(
                workspace,
                DiscoveryState(),
                (reviewed,),
                occurred_at="2026-09-11T19:05:00Z",
            )
            backlog = load_indexes(workspace).backlog

            self.assertEqual(outcome.created_job_ids, ("JOB-000001",))
            self.assertEqual(backlog["jobs"][0]["job_id"], "JOB-000001")
            self.assertTrue(
                (workspace.jobs / "JOB-000001" / "job.json").is_file()
            )


if __name__ == "__main__":
    unittest.main()
