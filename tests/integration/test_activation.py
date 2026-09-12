import tempfile
import unittest
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from career_pipeline.automation_policy import (
    default_discovery_schedule,
    lifecycle_available,
)
from career_pipeline.onboarding import (
    CONNECTORS,
    OnboardingState,
    record_connector_decision,
    record_profile_approval,
    save_onboarding_state,
)
from career_pipeline.readiness import check_readiness
from career_pipeline.workspace import create_workspace, preserve_source_resume


class ActivationScenarioTests(unittest.TestCase):
    def test_ready_with_every_connector_declined_and_public_sources(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            paths = create_workspace(Path(raw) / "Synthetic-Career")
            profile = paths.profile / "Career_Profile.md"
            criteria = paths.profile / "Search_Criteria.md"
            profile.write_text(
                "Synthetic approved profile\n\nEV-SYN-001: Fictional evidence.\n",
                encoding="utf-8",
            )
            criteria.write_text("Synthetic approved criteria\n", encoding="utf-8")
            (paths.profile / "Writing_Preferences.md").write_text(
                "Synthetic preferences\n", encoding="utf-8"
            )
            source = Path(raw) / "Synthetic_Resume.txt"
            source.write_text(
                "Synthetic source resume\n", encoding="utf-8"
            )
            preserve_source_resume(source, paths)
            state = OnboardingState.at("readiness")
            for connector in CONNECTORS:
                state = record_connector_decision(state, connector, "declined", ())
            state = record_profile_approval(
                state,
                hashlib.sha256(profile.read_bytes()).hexdigest(),
                hashlib.sha256(criteria.read_bytes()).hexdigest(),
            )
            config = {
                "schema_version": 2,
                "workspace_root": str(paths.root),
                "timezone": "America/New_York",
                "paths": {
                    "profile": "Profile",
                    "sources": "Sources",
                    "jobs": "Jobs",
                    "applications": "Applications",
                    "indexes": "Indexes",
                    "runs": "Runs",
                    "state": "State",
                },
                "profile_approved": True,
                "criteria_approved": True,
                "connectors": {},
                "enabled_sources": ["public_ats"],
                "discovery_schedule": default_discovery_schedule("America/New_York"),
                "packet_defaults": {
                    "resume_pages": 2,
                    "cover_letter_enabled": True,
                    "cover_letter_pages": 1,
                },
            }
            (paths.state / "config.json").write_text(json.dumps(config), encoding="utf-8")
            save_onboarding_state(paths.state / "onboarding-state.json", state)
            self.assertTrue(check_readiness(config, state).ready)

    def test_default_schedule_is_twice_each_weekday_in_user_timezone(self) -> None:
        schedule = default_discovery_schedule("America/New_York")
        self.assertEqual(schedule["weekdays"], ["MO", "TU", "WE", "TH", "FR"])
        self.assertEqual(schedule["runs_per_day"], 2)
        self.assertEqual(schedule["timezone"], "America/New_York")

    def test_lifecycle_requires_enabled_mail_or_calendar(self) -> None:
        state = OnboardingState.at("schedule")
        self.assertFalse(lifecycle_available(state))
        gmail = record_connector_decision(state, "gmail", "connected", ("search",))
        self.assertTrue(lifecycle_available(gmail))

    def test_ready_fixture_passes_readiness_cli(self) -> None:
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                sys.executable,
                str(root / "scripts" / "check_readiness.py"),
                "--fixture",
                str(root / "tests" / "fixtures" / "synthetic" / "onboarding" / "ready.json"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["ready"])


if __name__ == "__main__":
    unittest.main()
