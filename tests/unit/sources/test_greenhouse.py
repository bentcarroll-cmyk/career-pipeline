import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from career_pipeline.sources.base import SourceSnapshot
from career_pipeline.sources.greenhouse import normalize


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic" / "postings"


class GreenhouseAdapterTests(unittest.TestCase):
    def test_normalizes_greenhouse_without_inventing_missing_fields(self) -> None:
        payload = json.loads((FIXTURES / "greenhouse.json").read_text(encoding="utf-8"))
        jobs = normalize(SourceSnapshot("greenhouse", "2026-09-11T12:00:00Z", payload))

        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.employer, "Northstar Example Cooperative")
        self.assertEqual(job.requisition_id, "SYN-GH-101")
        self.assertEqual(job.responsibilities, ("Lead planning & operations.",))
        self.assertNotEqual(job.posting_url, job.application_url)
        self.assertIsNone(job.compensation_evidence)
        self.assertIn("compensation", job.uncertainties)

    def test_provider_shape_uses_explicit_employer_context(self) -> None:
        payload = json.loads((FIXTURES / "greenhouse.json").read_text(encoding="utf-8"))
        payload.pop("employer")

        job = normalize(
            SourceSnapshot(
                "greenhouse",
                "2026-09-11T12:00:00Z",
                payload,
                employer="Context Example Cooperative",
                board="context-board",
            )
        )[0]

        self.assertEqual(job.employer, "Context Example Cooperative")

    def test_provider_shape_without_employer_context_fails_closed(self) -> None:
        payload = json.loads((FIXTURES / "greenhouse.json").read_text(encoding="utf-8"))
        payload.pop("employer")

        with self.assertRaisesRegex(ValueError, "employer context"):
            normalize(SourceSnapshot("greenhouse", "2026-09-11T12:00:00Z", payload))


if __name__ == "__main__":
    unittest.main()
