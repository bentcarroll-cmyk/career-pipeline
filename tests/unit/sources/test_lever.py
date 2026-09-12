import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from career_pipeline.sources.base import SourceSnapshot
from career_pipeline.sources.lever import normalize


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic" / "postings"


class LeverAdapterTests(unittest.TestCase):
    def test_normalizes_documented_lever_shape_with_explicit_board_context(self) -> None:
        payload = json.loads((FIXTURES / "lever.json").read_text(encoding="utf-8"))
        job = normalize(
            SourceSnapshot(
                "lever",
                "2026-09-11T12:00:00Z",
                payload,
                employer="Harbor Example Labs",
                board="harbor-example",
            )
        )[0]

        self.assertEqual(job.team, "Strategy")
        self.assertEqual(job.location, "Remote — United States")
        self.assertEqual(job.application_url, "https://jobs.example/apply/SYN-LEV-202")
        self.assertEqual(job.source_record_id, "synthetic-lever-record")
        self.assertEqual(job.requisition_id, "lever:harbor-example:synthetic-lever-record")
        self.assertEqual(job.workplace_model, "remote")
        self.assertEqual(
            job.responsibilities,
            (
                "Build a fictional annual planning system.",
                "Outcomes: Create a measurable operating cadence.",
                "Collaboration: Partner with synthetic leaders.",
                "Closing details for this fictional role.",
            ),
        )

    def test_omitted_optional_lever_fields_remain_explicitly_unknown(self) -> None:
        job = normalize(
            SourceSnapshot(
                "lever", "2026-09-11T12:00:00Z",
                [{"id": "minimal", "text": "Synthetic role", "hostedUrl": "https://jobs.example/minimal"}],
                employer="Example Employer", board="example",
            )
        )[0]
        self.assertIsNone(job.location)
        self.assertIsNone(job.workplace_model)
        self.assertEqual(job.responsibilities, ())
        self.assertIn("workplace_model", job.uncertainties)

    def test_normalize_cli_routes_explicit_lever_context(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "jobs.json"
            root = Path(__file__).resolve().parents[3]
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts" / "normalize_jobs.py"),
                    "--adapter", "lever",
                    "--source", "lever",
                    "--fetched-at", "2026-09-11T12:00:00Z",
                    "--input", str(FIXTURES / "lever.json"),
                    "--output", str(output),
                    "--employer", "Harbor Example Labs",
                    "--board", "harbor-example",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            job = json.loads(output.read_text())["jobs"][0]
            self.assertEqual(job["employer"], "Harbor Example Labs")
            self.assertEqual(
                job["requisition_id"],
                "lever:harbor-example:synthetic-lever-record",
            )


if __name__ == "__main__":
    unittest.main()
