import tempfile
import unittest
import hashlib
import json
from pathlib import Path
from typing import Optional

from career_pipeline.onboarding import (
    CONNECTORS,
    OnboardingState,
    record_connector_decision,
    record_profile_approval,
    save_onboarding_state,
)
from career_pipeline.readiness import check_readiness
from career_pipeline.workspace import create_workspace, preserve_source_resume


class ReadinessTests(unittest.TestCase):
    def _approved_state(self, paths: Path) -> OnboardingState:
        profile = paths / "Profile" / "Career_Profile.md"
        criteria = paths / "Profile" / "Search_Criteria.md"
        state = OnboardingState.at("readiness")
        for connector in CONNECTORS:
            state = record_connector_decision(state, connector, "declined", ())
        return record_profile_approval(
            state,
            hashlib.sha256(profile.read_bytes()).hexdigest(),
            hashlib.sha256(criteria.read_bytes()).hexdigest(),
        )

    def _config(
        self, root: Path, enabled_sources: Optional[list[str]] = None
    ) -> dict[str, object]:
        return {
            "schema_version": 2,
            "workspace_root": str(root),
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
            "enabled_sources": enabled_sources or ["public_ats"],
            "discovery_schedule": {
                "frequency": "weekday",
                "weekdays": ["MO", "TU", "WE", "TH", "FR"],
                "runs_per_day": 2,
                "timezone": "America/New_York",
            },
            "packet_defaults": {
                "resume_pages": 2,
                "cover_letter_enabled": True,
                "cover_letter_pages": 1,
            },
        }

    def _ready_workspace(self, base: Path) -> tuple[Path, dict[str, object], OnboardingState]:
        paths = create_workspace(base / "Synthetic-Career")
        profile = paths.profile / "Career_Profile.md"
        criteria = paths.profile / "Search_Criteria.md"
        profile.write_text("Synthetic approved profile\n", encoding="utf-8")
        criteria.write_text("Synthetic approved criteria\n", encoding="utf-8")
        (paths.profile / "Writing_Preferences.md").write_text(
            "Synthetic writing preferences\n", encoding="utf-8"
        )
        source = base / "Synthetic_Resume.txt"
        source.write_text("Synthetic source resume\n", encoding="utf-8")
        preserve_source_resume(source, paths)
        state = self._approved_state(paths.root)
        config = self._config(paths.root)
        (paths.state / "config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        save_onboarding_state(paths.state / "onboarding-state.json", state)
        return paths.root, config, state

    def test_profile_local_store_and_connector_decisions_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            paths = create_workspace(Path(raw) / "Synthetic-Career")
            profile = paths.profile / "Career_Profile.md"
            criteria = paths.profile / "Search_Criteria.md"
            profile.write_text("Synthetic approved profile\n", encoding="utf-8")
            criteria.write_text("Synthetic approved criteria\n", encoding="utf-8")
            (paths.profile / "Writing_Preferences.md").write_text(
                "Synthetic writing preferences\n", encoding="utf-8"
            )
            source = Path(raw) / "Synthetic_Resume.txt"
            source.write_text("Synthetic source resume\n", encoding="utf-8")
            preserve_source_resume(source, paths)
            state = OnboardingState.at("readiness")
            config = self._config(paths.root)
            (paths.state / "config.json").write_text(json.dumps(config), encoding="utf-8")
            save_onboarding_state(paths.state / "onboarding-state.json", state)
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
            save_onboarding_state(paths.state / "onboarding-state.json", state)
            self.assertTrue(check_readiness(config, state).ready)
            self.assertTrue((paths.indexes / "backlog.json").is_file())

            invalid = {**config, "packet_defaults": {"resume_pages": 1}}
            (paths.state / "config.json").write_text(
                json.dumps(invalid), encoding="utf-8"
            )
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

    def test_resume_must_match_its_persisted_receipt_and_remain_a_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, config, state = self._ready_workspace(Path(raw))
            resume = root / "Sources" / "Resume_Original.txt"

            resume.write_bytes(b"X" * resume.stat().st_size)
            self.assertIn("resume_hash_mismatch", check_readiness(config, state).failure_codes)

            receipt = json.loads((root / "State" / "source-resume-receipt.json").read_text())
            resume.unlink()
            resume.mkdir()
            self.assertIn("resume_not_regular_file", check_readiness(config, state).failure_codes)
            self.assertEqual(receipt["destination"], "Sources/Resume_Original.txt")

    def test_resume_receipt_must_bind_the_preserved_resume_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, config, state = self._ready_workspace(Path(raw))
            receipt_path = root / "State" / "source-resume-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            (root / "Sources" / "other.txt").write_bytes(
                (root / "Sources" / "Resume_Original.txt").read_bytes()
            )
            receipt["destination"] = "Sources/other.txt"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            self.assertIn(
                "resume_receipt_destination_mismatch",
                check_readiness(config, state).failure_codes,
            )

    def test_readiness_uses_persisted_configuration_and_onboarding_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, config, state = self._ready_workspace(Path(raw))
            caller_config = {**config, "timezone": "UTC"}
            self.assertIn(
                "persisted_config_mismatch",
                check_readiness(caller_config, state).failure_codes,
            )

            (root / "State" / "onboarding-state.json").write_text(
                "not valid JSON", encoding="utf-8"
            )
            self.assertIn(
                "persisted_onboarding_invalid",
                check_readiness(config, state).failure_codes,
            )

    def test_persisted_configuration_must_use_the_current_workspace_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, config, state = self._ready_workspace(Path(raw))
            malformed = {**config, "schema_version": 99}
            (root / "State" / "config.json").write_text(
                json.dumps(malformed), encoding="utf-8"
            )

            self.assertIn(
                "persisted_config_invalid",
                check_readiness(malformed, state).failure_codes,
            )

    def test_discovery_schedule_must_have_a_matching_timezone_and_valid_cadence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, config, state = self._ready_workspace(Path(raw))
            schedule_timezone_mismatch = {
                **config,
                "discovery_schedule": {
                    **config["discovery_schedule"],
                    "timezone": "UTC",
                },
            }
            (root / "State" / "config.json").write_text(
                json.dumps(schedule_timezone_mismatch), encoding="utf-8"
            )
            self.assertIn(
                "discovery_schedule_timezone_mismatch",
                check_readiness(schedule_timezone_mismatch, state).failure_codes,
            )

            invalid_cadence = {
                **schedule_timezone_mismatch,
                "discovery_schedule": {
                    **schedule_timezone_mismatch["discovery_schedule"],
                    "timezone": "America/New_York",
                    "runs_per_day": 0,
                },
            }
            (root / "State" / "config.json").write_text(
                json.dumps(invalid_cadence), encoding="utf-8"
            )
            self.assertIn(
                "discovery_schedule_invalid",
                check_readiness(invalid_cadence, state).failure_codes,
            )

    def test_malformed_timezone_and_weekday_values_return_failure_codes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, config, state = self._ready_workspace(Path(raw))
            malformed_timezone = {**config, "timezone": []}
            (root / "State" / "config.json").write_text(
                json.dumps(malformed_timezone), encoding="utf-8"
            )
            self.assertIn(
                "timezone_invalid", check_readiness(malformed_timezone, state).failure_codes
            )

            malformed_weekdays = {
                **config,
                "discovery_schedule": {
                    **config["discovery_schedule"],
                    "weekdays": [["MO"]],
                },
            }
            (root / "State" / "config.json").write_text(
                json.dumps(malformed_weekdays), encoding="utf-8"
            )
            self.assertIn(
                "discovery_schedule_invalid",
                check_readiness(malformed_weekdays, state).failure_codes,
            )

    def test_export_or_enrichment_actions_do_not_activate_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, config, state = self._ready_workspace(Path(raw))
            state = record_connector_decision(
                state, "linear", "connected", ("create_issue",)
            )
            export_only = self._config(root, ["linear"])
            (root / "State" / "config.json").write_text(
                json.dumps(export_only), encoding="utf-8"
            )
            save_onboarding_state(root / "State" / "onboarding-state.json", state)
            self.assertIn("no_discovery_source", check_readiness(export_only, state).failure_codes)

            state = record_connector_decision(state, "indeed", "connected", ("job_search",))
            searchable = self._config(root, ["indeed"])
            (root / "State" / "config.json").write_text(
                json.dumps(searchable), encoding="utf-8"
            )
            save_onboarding_state(root / "State" / "onboarding-state.json", state)
            self.assertTrue(check_readiness(searchable, state).ready)

    def test_page_extraction_alone_does_not_activate_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, _config, state = self._ready_workspace(Path(raw))
            for connector in ("firecrawl", "browser"):
                connected = record_connector_decision(
                    state, connector, "connected", ("page_extract",)
                )
                config = self._config(root, [connector])
                (root / "State" / "config.json").write_text(
                    json.dumps(config), encoding="utf-8"
                )
                save_onboarding_state(root / "State" / "onboarding-state.json", connected)

                self.assertIn(
                    "no_discovery_source", check_readiness(config, connected).failure_codes
                )

    def test_onboarding_must_have_reached_readiness_before_activation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, config, _state = self._ready_workspace(Path(raw))
            profile = root / "Profile" / "Career_Profile.md"
            criteria = root / "Profile" / "Search_Criteria.md"
            early = OnboardingState.at("privacy")
            for connector in CONNECTORS:
                early = record_connector_decision(early, connector, "declined", ())
            early = record_profile_approval(
                early,
                hashlib.sha256(profile.read_bytes()).hexdigest(),
                hashlib.sha256(criteria.read_bytes()).hexdigest(),
            )
            save_onboarding_state(root / "State" / "onboarding-state.json", early)

            self.assertIn("onboarding_not_ready", check_readiness(config, early).failure_codes)


if __name__ == "__main__":
    unittest.main()
