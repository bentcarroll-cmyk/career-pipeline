import tempfile
import unittest
from pathlib import Path

from career_pipeline.onboarding import (
    CONNECTORS,
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
            state = OnboardingState.at("connectors")
            for connector in CONNECTORS:
                state = record_connector_decision(state, connector, "declined", ())
            state = advance_onboarding(
                state,
                "resume",
                {"all_connector_decisions_recorded": True},
            )
            save_onboarding_state(path, state)

            resumed = load_onboarding_state(path)

        self.assertEqual(resumed, state)
        self.assertEqual(
            set(resumed.connectors),
            set(CONNECTORS),
        )
        self.assertTrue(
            resumed.receipts["connectors"]["all_connector_decisions_recorded"]
        )

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
