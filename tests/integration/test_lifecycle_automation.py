import unittest

from career_pipeline.automation_policy import render_automation
from career_pipeline.reconciliation import (
    LifecycleCandidate,
    LifecycleEvidence,
    classify_lifecycle_evidence,
)


class LifecycleAutomationTests(unittest.TestCase):
    def test_prompt_is_read_only_outside_verified_linear_status(self) -> None:
        prompt = render_automation(
            "lifecycle",
            {
                "workspace_config": "State/config.json",
                "timezone": "America/New_York"
            },
        )
        self.assertIn("Never send", prompt)
        self.assertIn("minimal receipt", prompt)

    def test_wrong_role_does_not_update(self) -> None:
        candidate = LifecycleCandidate(
            "JOB-302", "Example Organization", "Product Lead", "SYN-302"
        )
        evidence = LifecycleEvidence(
            "gmail",
            "message-hash-4",
            "2026-09-11T12:00:00Z",
            "Example Organization",
            "Operations Lead",
            "SYN-301",
            "rejection",
        )
        self.assertEqual(
            classify_lifecycle_evidence(evidence, (candidate,)).action,
            "needs_review",
        )


if __name__ == "__main__":
    unittest.main()
