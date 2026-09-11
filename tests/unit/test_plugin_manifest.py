import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class PluginManifestTests(unittest.TestCase):
    def test_manifest_exposes_exactly_four_skills(self) -> None:
        manifest_path = ROOT / ".codex-plugin" / "plugin.json"
        self.assertTrue(manifest_path.is_file(), "plugin manifest must exist")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "career-pipeline")
        self.assertRegex(manifest["version"], re.compile(r"^\d+\.\d+\.\d+$"))
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertNotIn("apps", manifest)
        self.assertNotIn("mcpServers", manifest)

        skill_names = {
            path.parent.name
            for path in (ROOT / "skills").glob("*/SKILL.md")
        }
        self.assertEqual(
            skill_names,
            {"onboard", "discover-jobs", "review-backlog", "prepare-application"},
        )

    def test_onboard_skill_links_every_progressive_reference(self) -> None:
        skill_root = ROOT / "skills" / "onboard"
        skill_text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        expected = {
            "privacy-and-consent.md",
            "connectors.md",
            "interview.md",
            "readiness-and-activation.md",
        }
        discovered = {path.name for path in (skill_root / "references").glob("*.md")}
        self.assertTrue(expected.issubset(discovered))
        for name in expected:
            self.assertIn(f"references/{name}", skill_text)
        self.assertTrue((skill_root / "agents" / "openai.yaml").is_file())


if __name__ == "__main__":
    unittest.main()
