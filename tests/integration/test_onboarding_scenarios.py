import tempfile
import unittest
from pathlib import Path

from career_pipeline.capabilities import LINEAR_REQUIRED_ACTIONS, OPTIONAL_CONNECTORS
from career_pipeline.onboarding import (
    OnboardingState,
    advance_onboarding,
    load_onboarding_state,
    record_connector_decision,
    record_profile_approval,
    save_onboarding_state,
)


class OnboardingScenarioTests(unittest.TestCase):
    def test_interrupted_state_resumes_with_receipts_and_declines(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "onboarding-state.json"
            state = OnboardingState.at("linear")
            state = record_connector_decision(
                state,
                "linear",
                "connected",
                LINEAR_REQUIRED_ACTIONS,
                LINEAR_REQUIRED_ACTIONS,
            )
            state = advance_onboarding(
                state,
                "optional_connectors",
                {"project_id": "synthetic-project", "verified": True},
            )
            for connector in OPTIONAL_CONNECTORS:
                state = record_connector_decision(state, connector, "declined", ())
            save_onboarding_state(path, state)

            resumed = load_onboarding_state(path)

        self.assertEqual(resumed, state)
        self.assertEqual(
            set(resumed.connectors),
            {"linear", *OPTIONAL_CONNECTORS},
        )
        self.assertTrue(resumed.receipts["linear"]["verified"])

    def test_later_profile_approval_replaces_earlier_hashes(self) -> None:
        state = record_profile_approval(
            OnboardingState.at("profile"), "resume-derived", "initial-criteria"
        )
        corrected = record_profile_approval(
            state, "user-corrected", "corrected-criteria"
        )
        self.assertEqual(corrected.profile_hash, "user-corrected")
        self.assertEqual(corrected.criteria_hash, "corrected-criteria")


if __name__ == "__main__":
    unittest.main()
