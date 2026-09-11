import unittest

from career_pipeline.onboarding import (
    InvalidTransition,
    OnboardingState,
    advance_onboarding,
    record_connector_decision,
    record_profile_approval,
)


class OnboardingTests(unittest.TestCase):
    def test_optional_decline_is_remembered_without_blocking_other_choices(self) -> None:
        state = OnboardingState.at("optional_connectors")
        updated = record_connector_decision(state, "notion", "declined", ())
        updated = record_connector_decision(updated, "github", "connected", ("read",))

        self.assertEqual(updated.connectors["notion"].decision, "declined")
        self.assertEqual(updated.connectors["github"].capabilities, ("read",))
        self.assertEqual(updated.stage, "optional_connectors")

    def test_installed_connector_missing_action_is_unavailable(self) -> None:
        state = OnboardingState.at("optional_connectors")
        updated = record_connector_decision(
            state,
            "linkedin",
            "connected",
            ("people_search",),
            expected_capabilities=("job_search",),
        )
        self.assertEqual(updated.connectors["linkedin"].decision, "unavailable")
        self.assertEqual(updated.connectors["linkedin"].capabilities, ("people_search",))

    def test_linear_decline_cannot_advance_to_active(self) -> None:
        state = OnboardingState.at("readiness")
        state = record_connector_decision(state, "linear", "declined", ())
        with self.assertRaises(InvalidTransition):
            advance_onboarding(state, "active", {"ready": True})

    def test_profile_approval_records_current_hashes(self) -> None:
        state = OnboardingState.at("profile")
        approved = record_profile_approval(state, "profile-hash", "criteria-hash")
        self.assertEqual(approved.profile_hash, "profile-hash")
        self.assertEqual(approved.criteria_hash, "criteria-hash")


if __name__ == "__main__":
    unittest.main()
