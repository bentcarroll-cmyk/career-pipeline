import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from career_pipeline.checkpoints import DiscoveryState
from career_pipeline.discovery import ReviewedJob, deliver_reviewed_jobs
from career_pipeline.evaluation import EvidenceClaim, JobAssessment
from career_pipeline.indexes import load_indexes
from career_pipeline.onboarding import OnboardingState, save_onboarding_state
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
            profile_text = "# Profile\n\n- EV-011: Synthetic operations evidence.\n"
            criteria_text = "# Synthetic approved criteria\n"
            (workspace.profile / "Career_Profile.md").write_text(profile_text)
            (workspace.profile / "Search_Criteria.md").write_text(criteria_text)
            profile_hash = hashlib.sha256(profile_text.encode()).hexdigest()
            criteria_hash = hashlib.sha256(criteria_text.encode()).hexdigest()
            save_onboarding_state(
                workspace.state / "onboarding-state.json",
                OnboardingState(profile_hash=profile_hash, criteria_hash=criteria_hash),
            )
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
                    profile_hash=profile_hash,
                    criteria_hash=criteria_hash,
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
