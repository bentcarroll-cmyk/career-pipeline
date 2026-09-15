import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ResumeIdentityCheckTests(unittest.TestCase):
    def test_cli_handles_section_boundaries_and_wrapped_headlines(self) -> None:
        cases = (
            (
                "PRODUCT STRATEGY | CUSTOMER DISCOVERY\nPROFESSIONAL SUMMARY\n"
                "Product leader.\nWORK EXPERIENCE\nPrior Company\nStaff Product Manager\n",
                "Staff Product Manager", 0, [],
            ),
            (
                "Senior Director, Strategy and\nOperations\nWORK EXPERIENCE\nPrior Company\n",
                "Senior Director, Strategy and Operations", 1,
                ["target_role_title_in_resume_header"],
            ),
        )
        script = Path(__file__).resolve().parents[2] / "scripts/check_resume_identity.py"
        for body, title, exit_code, errors in cases:
            with self.subTest(title=title), tempfile.TemporaryDirectory() as raw:
                resume = Path(raw) / "resume.txt"
                receipt = Path(raw) / "identity.json"
                resume.write_text("SYNTHETIC CANDIDATE\n" + body)
                result = subprocess.run(
                    [sys.executable, str(script), "--resume-text", str(resume),
                     "--employer", "Target Company", "--title", title,
                     "--output", str(receipt)],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, exit_code, result.stderr)
                self.assertEqual(json.loads(receipt.read_text())["errors"], errors)

    def test_cli_rejects_target_title_in_identity_block(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            resume = Path(raw) / "resume.txt"
            receipt = Path(raw) / "resume-identity.json"
            resume.write_text(
                "SYNTHETIC CANDIDATE\n"
                "Anywhere, US | synthetic contact\n"
                "Staff Product Manager | Headway\n"
                "EXECUTIVE PROFILE\n"
                "Product and operations leader.\n"
            )
            script = Path(__file__).resolve().parents[2] / "scripts/check_resume_identity.py"

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--resume-text",
                    str(resume),
                    "--employer",
                    "Headway (NY)",
                    "--title",
                    "Staff Product Manager",
                    "--output",
                    str(receipt),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(
                json.loads(receipt.read_text()),
                {
                    "employer": "Headway (NY)",
                    "errors": ["target_role_title_in_resume_header"],
                    "title": "Staff Product Manager",
                    "valid": False,
                },
            )

    def test_cli_rejects_requested_start_date_below_experience(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            resume = Path(raw) / "resume.txt"
            receipt = Path(raw) / "resume-content.json"
            resume.write_text(
                "SYNTHETIC CANDIDATE\n"
                "Anywhere, US | synthetic contact\n"
                "AI TRANSFORMATION | OPERATING MODELS | ADOPTION\n"
                "EXECUTIVE PROFILE\n"
                "Operations leader.\n"
                "ADDITIONAL\n"
                "Preferred start date: January 5, 2027; earlier start negotiable.\n"
            )
            script = Path(__file__).resolve().parents[2] / "scripts/check_resume_identity.py"

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--resume-text",
                    str(resume),
                    "--employer",
                    "Synthetic Employer",
                    "--title",
                    "Transformation Director",
                    "--output",
                    str(receipt),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(
                json.loads(receipt.read_text())["errors"],
                ["requested_start_date_in_resume"],
            )


if __name__ == "__main__":
    unittest.main()
