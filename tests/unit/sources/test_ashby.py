import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from career_pipeline.sources.ashby import normalize
from career_pipeline.sources.base import SourceSnapshot


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic" / "postings"


class AshbyAdapterTests(unittest.TestCase):
    def test_normalizes_ashby_compensation_without_guessing_travel(self) -> None:
        payload = json.loads((FIXTURES / "ashby.json").read_text(encoding="utf-8"))
        job = normalize(SourceSnapshot("ashby", "2026-09-11T12:00:00Z", payload))[0]

        self.assertEqual(job.compensation_evidence, "$180,000–$210,000 fictional range")
        self.assertIsNone(job.travel)
        self.assertIn("travel", job.uncertainties)
        self.assertEqual(job.verification_status, "source_snapshot")

    def test_provider_shape_uses_explicit_employer_context(self) -> None:
        payload = json.loads((FIXTURES / "ashby.json").read_text(encoding="utf-8"))
        payload.pop("employer")

        job = normalize(
            SourceSnapshot(
                "ashby",
                "2026-09-11T12:00:00Z",
                payload,
                employer="Context Example Labs",
                board="context-board",
            )
        )[0]

        self.assertEqual(job.employer, "Context Example Labs")

    def test_provider_shape_without_employer_context_fails_closed(self) -> None:
        payload = json.loads((FIXTURES / "ashby.json").read_text(encoding="utf-8"))
        payload.pop("employer")

        with self.assertRaisesRegex(ValueError, "employer context"):
            normalize(SourceSnapshot("ashby", "2026-09-11T12:00:00Z", payload))


if __name__ == "__main__":
    unittest.main()
