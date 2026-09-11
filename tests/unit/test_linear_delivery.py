import unittest

from career_pipeline.evaluation import EvidenceClaim, JobAssessment
from career_pipeline.linear_delivery import (
    DeliveryVerificationError,
    build_issue_payload,
    verify_issue_readback,
)
from career_pipeline.sources.base import SourceSnapshot
from career_pipeline.sources.generic import normalize


def job():
    return normalize(
        SourceSnapshot(
            "public-search",
            "2026-09-11T12:00:00Z",
            [
                {
                    "source_record_id": "linear-source-record",
                    "requisition_id": "SYN-LIN-601",
                    "employer": "Example Organization",
                    "title": "Operations Lead",
                    "responsibilities": ["Build an operating cadence."],
                    "location": "New York, NY",
                    "posting_url": "https://jobs.example/postings/SYN-LIN-601",
                    "application_url": "https://jobs.example/apply/SYN-LIN-601"
                }
            ],
        )
    )[0]


def assessment(disposition: str = "strong_match"):
    return JobAssessment(
        disposition=disposition,
        role_to_profile_fit="Matches approved operating-system work.",
        strengths=(EvidenceClaim("EV-001", "Built a fictional planning cadence."),),
        gaps=("Sector experience needs confirmation.",),
        uncertainties=("Compensation is not stated.",),
    )


class LinearDeliveryTests(unittest.TestCase):
    def test_builds_complete_qualifying_payload(self) -> None:
        payload = build_issue_payload(
            job(),
            assessment(),
            {
                "team_id": "synthetic-team",
                "project_id": "synthetic-project",
            },
        )
        self.assertEqual(payload.labels, ("Strong Match",))
        self.assertIn("SYN-LIN-601", payload.description)
        self.assertIn("Evidence-supported strengths", payload.description)
        self.assertEqual(payload.application_url, "https://jobs.example/apply/SYN-LIN-601")

    def test_non_match_cannot_be_built_for_linear(self) -> None:
        with self.assertRaises(ValueError):
            build_issue_payload(
                job(),
                assessment("non_match"),
                {"team_id": "synthetic-team", "project_id": "synthetic-project"},
            )

    def test_readback_must_match_exact_destination_and_body(self) -> None:
        payload = build_issue_payload(
            job(),
            assessment(),
            {"team_id": "synthetic-team", "project_id": "synthetic-project"},
        )
        actual = payload.to_readback("SYN-777")
        receipt = verify_issue_readback(payload, actual)
        self.assertTrue(receipt.verified)
        self.assertEqual(receipt.issue_id, "SYN-777")

        changed = {**actual, "project_id": "wrong-project"}
        with self.assertRaises(DeliveryVerificationError):
            verify_issue_readback(payload, changed)


if __name__ == "__main__":
    unittest.main()
