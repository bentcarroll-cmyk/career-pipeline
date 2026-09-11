from __future__ import annotations

import tempfile
import unittest
import zipfile
import subprocess
import sys
from pathlib import Path

from career_pipeline.packaging import build_plugin_archive
from career_pipeline.privacy import scan_tree


class PackagingTests(unittest.TestCase):
    def test_archive_is_deterministic_allowlisted_and_private(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            first = build_plugin_archive(repository, output / "first")
            second = build_plugin_archive(repository, output / "second")

            self.assertEqual(first.sha256, second.sha256)
            self.assertEqual(first.archive.read_bytes(), second.archive.read_bytes())
            with zipfile.ZipFile(first.archive) as bundle:
                names = bundle.namelist()
                self.assertEqual(names, sorted(names))
                self.assertIn(".codex-plugin/plugin.json", names)
                self.assertIn(".agents/plugins/marketplace.json", names)
                self.assertIn("skills/onboard/SKILL.md", names)
                self.assertIn("docs/private-beta-installation.md", names)
                self.assertIn("CHANGELOG.md", names)
                self.assertFalse(any(name.startswith("tests/") for name in names))
                self.assertFalse(any("__pycache__" in name for name in names))
                self.assertFalse(any(name.endswith((".pdf", ".doc", ".docx")) for name in names))
                self.assertTrue(
                    all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in bundle.infolist())
                )
            self.assertEqual(scan_tree(first.archive), [])
            validation = subprocess.run(
                [sys.executable, str(repository / "scripts" / "validate_plugin.py"), str(first.archive)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)


if __name__ == "__main__":
    unittest.main()
