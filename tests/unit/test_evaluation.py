import unittest

from career_pipeline.evaluation import (
    EvidenceClaim,
    JobAssessment,
    validate_assessment,
)
from career_pipeline.sources.generic import normalize
from career_pipeline.sources.base import SourceSnapshot


def synthetic_job():
    return normalize(
        SourceSnapshot(
            "public-search",
            "2026-09-11T12:00:00Z",
            [
                {
                    "source_record_id": "record-1",
                    "requisition_id": "SYN-501",
                    "employer": "Example Organization",
                    "title": "Operations Lead",
                    "responsibilities": ["Build an operating cadence."],
                    "posting_url": "https://jobs.example/postings/SYN-501",
                    "application_url": "https://jobs.example/apply/SYN-501"
                }
            ],
        )
    )[0]


class EvaluationTests(unittest.TestCase):
    def test_positive_claim_must_reference_profile_evidence(self) -> None:
        assessment = JobAssessment(
            disposition="strong_match",
            role_to_profile_fit="Strong responsibility alignment.",
            strengths=(EvidenceClaim("EV-MISSING", "Built a planning cadence."),),
            gaps=("Industry depth needs confirmation.",),
            uncertainties=("Compensation is not stated.",),
        )
        errors = validate_assessment(
            synthetic_job(),
            {"evidence": {"EV-001": "Synthetic planning evidence."}},
            assessment,
        )
        self.assertIn("unsupported_strength", {error.code for error in errors})

    def test_non_match_can_be_recorded_without_positive_claim(self) -> None:
        assessment = JobAssessment(
            disposition="non_match",
            role_to_profile_fit="Required location conflicts with approved criteria.",
            strengths=(),
            gaps=("Location is incompatible.",),
            uncertainties=(),
        )
        self.assertEqual(validate_assessment(synthetic_job(), {"evidence": {}}, assessment), [])


if __name__ == "__main__":
    unittest.main()
