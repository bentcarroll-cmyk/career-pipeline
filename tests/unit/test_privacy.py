import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from career_pipeline.privacy import Finding, scan_tree


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

    def test_scan_detects_quoted_structured_credential_keys_without_values(self) -> None:
        synthetic_value = "synthetic-secret-value"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "runtime.json").write_text(
                '{"api_key": "' + synthetic_value + '"}', encoding="utf-8"
            )
            (root / "runtime.yaml").write_text(
                "client_secret: '" + synthetic_value + "'\n", encoding="utf-8"
            )
            (root / "runtime.toml").write_text(
                'access_token = "' + synthetic_value + '"\n', encoding="utf-8"
            )
            (root / ".env").write_text(
                "PASSWORD='" + synthetic_value + "'\n", encoding="utf-8"
            )
            (root / "environment.env").write_text(
                "OPENAI_API_KEY='" + synthetic_value + "'\n", encoding="utf-8"
            )

            findings = scan_tree(root)

        self.assertEqual(
            {finding.path for finding in findings},
            {".env", "environment.env", "runtime.json", "runtime.toml", "runtime.yaml"},
        )
        self.assertTrue(all(finding.rule == "credential-assignment" for finding in findings))
        self.assertNotIn(synthetic_value, repr(findings))

    def test_scan_flags_obvious_credential_bearing_file_without_reading_a_value(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "credentials.json").write_text("{}", encoding="utf-8")

            findings = scan_tree(root)

        self.assertEqual(
            findings,
            [Finding("credentials.json", 0, "credential-bearing-file")],
        )

    def test_scan_flags_common_sensitive_file_names_and_keystores(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for name in (
                ".env",
                ".credentials",
                ".secrets",
                "id_rsa",
                "id_ed25519",
                "application.keystore",
                "release.jks",
            ):
                (root / name).write_text("synthetic", encoding="utf-8")

            findings = scan_tree(root)

        self.assertEqual(
            {finding.path for finding in findings},
            {
                ".env",
                ".credentials",
                ".secrets",
                "id_rsa",
                "id_ed25519",
                "application.keystore",
                "release.jks",
            },
        )
        self.assertTrue(all(finding.rule == "sensitive-file-name" for finding in findings))


if __name__ == "__main__":
    unittest.main()
