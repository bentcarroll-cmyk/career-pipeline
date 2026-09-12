import unittest

from career_pipeline.onboarding import (
    CONNECTORS,
    CONNECTOR_GROUPS,
    InvalidTransition,
    OnboardingState,
    advance_onboarding,
    record_post_activation_progress,
    record_connector_decision,
    record_profile_approval,
)


class OnboardingTests(unittest.TestCase):
    def test_optional_decline_is_remembered_without_blocking_other_choices(self) -> None:
        state = OnboardingState.at("connectors")
        updated = record_connector_decision(state, "notion", "declined", ())
        updated = record_connector_decision(updated, "github", "connected", ("read",))

        self.assertEqual(updated.connectors["notion"].decision, "declined")
        self.assertEqual(updated.connectors["github"].capabilities, ("read",))
        self.assertEqual(updated.stage, "connectors")

    def test_installed_connector_missing_action_is_unavailable(self) -> None:
        state = OnboardingState.at("connectors")
        updated = record_connector_decision(
            state,
            "linkedin",
            "connected",
            ("people_search",),
            expected_capabilities=("job_search",),
        )
        self.assertEqual(updated.connectors["linkedin"].decision, "unavailable")
        self.assertEqual(updated.connectors["linkedin"].capabilities, ("people_search",))

    def test_all_connectors_may_be_declined_before_activation(self) -> None:
        state = OnboardingState.at("readiness")
        for connector in CONNECTORS:
            state = record_connector_decision(state, connector, "declined", ())
        state = record_profile_approval(state, "profile-hash", "criteria-hash")

        active = advance_onboarding(state, "active", {"ready": True})

        self.assertEqual(active.stage, "active")

    def test_incomplete_connector_decisions_cannot_activate(self) -> None:
        state = record_profile_approval(
            OnboardingState.at("readiness"), "profile-hash", "criteria-hash"
        )
        with self.assertRaises(InvalidTransition):
            advance_onboarding(state, "active", {"ready": True})

    def test_profile_approval_records_current_hashes(self) -> None:
        state = OnboardingState.at("profile")
        approved = record_profile_approval(state, "profile-hash", "criteria-hash")
        self.assertEqual(approved.profile_hash, "profile-hash")
        self.assertEqual(approved.criteria_hash, "criteria-hash")

    def test_connector_deferral_is_distinct_and_grouped_by_purpose(self) -> None:
        self.assertEqual(
            {connector for group in CONNECTOR_GROUPS.values() for connector in group},
            set(CONNECTORS),
        )
        self.assertEqual(
            sum(len(group) for group in CONNECTOR_GROUPS.values()),
            len(CONNECTORS),
        )
        state = record_connector_decision(
            OnboardingState.quick_start(), "indeed", "deferred", ()
        )
        self.assertEqual(state.connectors["indeed"].decision, "deferred")

    def test_quick_start_follow_up_remains_resumable_after_activation(self) -> None:
        state = OnboardingState.quick_start()
        state = OnboardingState(
            stage="active",
            completed=state.completed,
            connectors={
                connector: record_connector_decision(
                    state, connector, "deferred", ()
                ).connectors[connector]
                for connector in CONNECTORS
            },
            receipts=state.receipts,
            profile_hash="profile-hash",
            criteria_hash="criteria-hash",
            mode="quick_start",
            post_activation=state.post_activation,
        )
        progressed = record_post_activation_progress(
            state, "interview", completed=True
        )

        self.assertEqual(progressed.post_activation["interview"], "completed")
        self.assertEqual(
            progressed.post_activation["connector_configuration"], "pending"
        )

    def test_post_activation_progress_requires_an_active_quick_start(self) -> None:
        with self.assertRaises(InvalidTransition):
            record_post_activation_progress(
                OnboardingState.quick_start(), "interview", completed=True
            )


if __name__ == "__main__":
    unittest.main()
