import tempfile
import unittest
import hashlib
from pathlib import Path

from career_pipeline.onboarding import (
    CONNECTORS,
    OnboardingState,
    record_connector_decision,
    record_profile_approval,
)
from career_pipeline.readiness import check_readiness
from career_pipeline.workspace import create_workspace


class ReadinessTests(unittest.TestCase):
    def test_profile_local_store_and_connector_decisions_are_required(self) -> None:
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
                "packet_defaults": {
                    "resume_pages": 2,
                    "cover_letter_enabled": True,
                    "cover_letter_pages": 1,
                },
            }
            report = check_readiness(config, state)
            self.assertIn("profile_not_approved", report.failure_codes)
            self.assertIn("connector_decisions_incomplete", report.failure_codes)

            for connector in CONNECTORS:
                state = record_connector_decision(state, connector, "declined", ())
            state = record_profile_approval(
                state,
                hashlib.sha256(profile.read_bytes()).hexdigest(),
                hashlib.sha256(criteria.read_bytes()).hexdigest(),
            )
            self.assertTrue(check_readiness(config, state).ready)
            self.assertTrue((paths.indexes / "backlog.json").is_file())

            invalid = {**config, "packet_defaults": {"resume_pages": 1}}
            self.assertIn(
                "packet_defaults_invalid",
                check_readiness(invalid, state).failure_codes,
            )

            (paths.state / "next-job-id.json").write_text(
                '{"schema_version": 1, "next_id": "invalid"}\n',
                encoding="utf-8",
            )
            self.assertIn(
                "local_store_invalid",
                check_readiness(config, state).failure_codes,
            )


if __name__ == "__main__":
    unittest.main()
