import tempfile
import unittest
from pathlib import Path

from career_pipeline.onboarding import OnboardingState, record_connector_decision, record_profile_approval
from career_pipeline.readiness import check_readiness
from career_pipeline.workspace import create_workspace


LINEAR_ACTIONS = (
    "search_issues",
    "create_issue",
    "read_issue",
    "manage_labels",
    "manage_views",
    "comment",
    "attach_file",
)


class ReadinessTests(unittest.TestCase):
    def test_profile_approval_and_linear_capabilities_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            paths = create_workspace(Path(raw) / "Synthetic-Career")
            state = OnboardingState.at("readiness")
            config = {
                "workspace_root": str(paths.root),
                "timezone": "America/New_York",
                "enabled_sources": ["public_ats"],
            }
            report = check_readiness(config, state)
            self.assertIn("linear_required", report.failure_codes)
            self.assertIn("profile_not_approved", report.failure_codes)

            state = record_connector_decision(
                state, "linear", "connected", LINEAR_ACTIONS, LINEAR_ACTIONS
            )
            state = record_profile_approval(state, "profile-hash", "criteria-hash")
            self.assertTrue(check_readiness(config, state).ready)


if __name__ == "__main__":
    unittest.main()
