import unittest

from career_pipeline.automation_policy import (
    UnsupportedAutomation,
    render_automation,
)


class AutomationPolicyTests(unittest.TestCase):
    def test_packet_automation_is_impossible(self) -> None:
        with self.assertRaises(UnsupportedAutomation):
            render_automation("prepare_application", {"timezone": "America/New_York"})

    def test_discovery_prompt_requires_approved_configuration(self) -> None:
        prompt = render_automation(
            "discovery",
            {
                "workspace_config": "State/config.json",
                "timezone": "America/New_York",
            },
        )
        self.assertIn("$discover-jobs", prompt)
        self.assertIn("Stay quiet", prompt)
        self.assertNotIn("prepare", prompt.lower())


if __name__ == "__main__":
    unittest.main()
