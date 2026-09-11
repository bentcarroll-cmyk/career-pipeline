import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class PrivacyScanTests(unittest.TestCase):
    def test_scan_rejects_synthetic_credential_without_printing_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "unsafe.txt").write_text(
                "api" + "_key=synthetic-secret-value",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "scan_private_data.py"), str(root)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("unsafe.txt", result.stdout)
        self.assertNotIn(raw, result.stdout)

    def test_repository_scan_does_not_flag_detector_definitions(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "scan_private_data.py"), str(ROOT)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
