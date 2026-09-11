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


if __name__ == "__main__":
    unittest.main()
