import tempfile
import unittest
import hashlib
from pathlib import Path

from career_pipeline.capabilities import OPTIONAL_CONNECTORS
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
            profile = paths.profile / "Career_Profile.md"
            criteria = paths.profile / "Search_Criteria.md"
            preferences = paths.profile / "Writing_Preferences.md"
            profile.write_text("Synthetic approved profile\n", encoding="utf-8")
            criteria.write_text("Synthetic approved criteria\n", encoding="utf-8")
            preferences.write_text("Synthetic writing preferences\n", encoding="utf-8")
            (paths.sources / "Resume_Original.txt").write_text(
                "Synthetic source resume\n", encoding="utf-8"
            )
            state = OnboardingState.at("readiness")
            config = {
                "workspace_root": str(paths.root),
                "timezone": "America/New_York",
                "enabled_sources": ["public_ats"],
                "linear": {
                    "workspace_id": "synthetic-workspace",
                    "team_id": "synthetic-team",
                    "project_id": "synthetic-project",
                },
                "packet_defaults": {
                    "resume_pages": 2,
                    "cover_letter_enabled": True,
                    "cover_letter_pages": 1,
                },
            }
            report = check_readiness(config, state)
            self.assertIn("linear_required", report.failure_codes)
            self.assertIn("profile_not_approved", report.failure_codes)

            state = record_connector_decision(
                state, "linear", "connected", LINEAR_ACTIONS, LINEAR_ACTIONS
            )
            for connector in OPTIONAL_CONNECTORS:
                state = record_connector_decision(state, connector, "declined", ())
            state = record_profile_approval(
                state,
                hashlib.sha256(profile.read_bytes()).hexdigest(),
                hashlib.sha256(criteria.read_bytes()).hexdigest(),
            )
            self.assertTrue(check_readiness(config, state).ready)

            invalid = {**config, "packet_defaults": {"resume_pages": 1}}
            self.assertIn(
                "packet_defaults_invalid",
                check_readiness(invalid, state).failure_codes,
            )


if __name__ == "__main__":
    unittest.main()
