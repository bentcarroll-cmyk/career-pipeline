import json
import tempfile
import unittest
from pathlib import Path

from career_pipeline.onboarding import (
    CONNECTORS,
    InvalidTransition,
    OnboardingState,
    advance_onboarding,
    load_onboarding_state,
    record_connector_decision,
    record_post_activation_progress,
    record_profile_approval,
    save_onboarding_state,
)


def ready_quick_start() -> OnboardingState:
    state = OnboardingState.quick_start()
    state = advance_onboarding(state, "workspace", {"privacy_approved": True})
    state = advance_onboarding(
        state, "resume", {"workspace_root": "/synthetic/workspace"}
    )
    state = advance_onboarding(
        state, "focus", {"resume_receipt": "source-resume-receipt.json"}
    )
    state = advance_onboarding(
        state,
        "profile",
        {
            "target_work": ["Synthetic operations leadership"],
            "hard_constraints": [],
        },
    )
    state = record_profile_approval(state, "profile-hash", "criteria-hash")
    state = advance_onboarding(
        state,
        "packet_defaults",
        {"profile_approved": True, "criteria_approved": True},
    )
    state = advance_onboarding(
        state,
        "connectors",
        {"resume_pages": 2, "cover_letter_enabled": True},
    )
    for connector in CONNECTORS:
        state = record_connector_decision(state, connector, "deferred", ())
    state = advance_onboarding(
        state, "schedule", {"connector_decisions_recorded": True}
    )
    return advance_onboarding(
        state,
        "readiness",
        {"enabled_sources": ["public_ats"]},
    )


class OnboardingScenarioTests(unittest.TestCase):
    def test_quick_start_is_resumable_through_activation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "onboarding-state.json"
            state = ready_quick_start()
            save_onboarding_state(path, state)

            resumed = load_onboarding_state(path)
            active = advance_onboarding(resumed, "active", {"ready": True})
            save_onboarding_state(path, active)
            loaded = load_onboarding_state(path)

        self.assertEqual(loaded.stage, "active")
        self.assertEqual(loaded.mode, "quick_start")
        self.assertTrue(all(item.decision == "deferred" for item in loaded.connectors.values()))
        self.assertEqual(
            loaded.post_activation,
            {"connector_configuration": "pending", "interview": "pending"},
        )

    def test_completed_connector_setup_reopens_when_a_choice_is_redeferred(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "onboarding-state.json"
            state = advance_onboarding(
                ready_quick_start(), "active", {"ready": True}
            )
            for connector in CONNECTORS:
                state = record_connector_decision(state, connector, "declined", ())
            state = record_post_activation_progress(
                state, "connector_configuration", completed=True
            )

            reopened = record_connector_decision(
                state, "github", "deferred", ()
            )
            save_onboarding_state(path, reopened)
            loaded = load_onboarding_state(path)

        self.assertEqual(
            loaded.post_activation["connector_configuration"], "pending"
        )
        self.assertEqual(loaded.connectors["github"].decision, "deferred")

    def test_quick_start_requires_focus_and_a_public_discovery_lane(self) -> None:
        state = OnboardingState.quick_start()
        state = advance_onboarding(state, "workspace", {"privacy_approved": True})
        state = advance_onboarding(state, "resume", {"workspace_root": "/synthetic"})
        state = advance_onboarding(state, "focus", {"resume_receipt": "receipt"})
        with self.assertRaises(InvalidTransition):
            advance_onboarding(state, "profile", {"target_work": ["Operations"]})

        ready = OnboardingState(
            stage="schedule",
            completed=(
                "privacy",
                "workspace",
                "resume",
                "focus",
                "profile",
                "packet_defaults",
                "connectors",
            ),
            connectors={
                connector: record_connector_decision(
                    OnboardingState.quick_start(), connector, "deferred", ()
                ).connectors[connector]
                for connector in CONNECTORS
            },
            receipts={"focus": {"target_work": ["Operations"], "hard_constraints": []}},
            profile_hash="profile-hash",
            criteria_hash="criteria-hash",
            mode="quick_start",
            post_activation={
                "connector_configuration": "pending",
                "interview": "pending",
            },
        )
        with self.assertRaises(InvalidTransition):
            advance_onboarding(ready, "readiness", {"enabled_sources": ["linear"]})

    def test_quick_start_resume_rejects_a_missing_required_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "onboarding-state.json"
            state = OnboardingState.quick_start()
            state = advance_onboarding(state, "workspace", {"privacy_approved": True})
            state = advance_onboarding(
                state, "resume", {"workspace_root": "/synthetic/workspace"}
            )
            state = advance_onboarding(
                state, "focus", {"resume_receipt": "source-resume-receipt.json"}
            )
            state = advance_onboarding(
                state,
                "profile",
                {"target_work": ["Operations"], "hard_constraints": []},
            )
            save_onboarding_state(path, state)
            raw_state = json.loads(path.read_text(encoding="utf-8"))
            del raw_state["receipts"]["focus"]
            path.write_text(json.dumps(raw_state), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_onboarding_state(path)

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
