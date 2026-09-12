from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from career_pipeline.criteria import (
    CriteriaError,
    CriteriaRule,
    SearchCriteria,
    evaluate_hard_filters,
    filter_then_assess,
    load_search_criteria,
)
from career_pipeline.evaluation import JobAssessment
from career_pipeline.sources.base import CandidateJob


def candidate(*, location: str | None = "Remote") -> CandidateJob:
    return CandidateJob(
        source="public-search",
        source_record_id="synthetic-criteria-1",
        requisition_id="SYN-CRITERIA-1",
        employer="Example Cooperative",
        title="Operations Lead",
        responsibilities=("Lead fictional operations.",),
        location=location,
        workplace_model="remote",
        travel=None,
        compensation_evidence=None,
        posting_url="https://jobs.example/postings/SYN-CRITERIA-1",
        application_url="https://jobs.example/apply/SYN-CRITERIA-1",
        team="Operations",
        posted_at=None,
        updated_at=None,
        deadline=None,
        verified_at="2026-09-11T18:00:00Z",
        verification_status="verified",
        raw_field_hash="a" * 64,
        uncertainties=("travel", "compensation"),
    )


def criteria(*rules: CriteriaRule) -> SearchCriteria:
    return SearchCriteria(
        readable_criteria_path="Profile/Search_Criteria.md",
        readable_criteria_sha256="b" * 64,
        rules=rules,
    )


class StructuredCriteriaTests(unittest.TestCase):
    def test_loader_requires_explicit_user_ownership_for_each_hard_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            readable = root / "Search_Criteria.md"
            readable.write_text("# Approved criteria\n", encoding="utf-8")
            structured = root / "Search_Criteria.json"
            structured.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "readable_criteria_path": "Profile/Search_Criteria.md",
                        "readable_criteria_sha256": hashlib.sha256(
                            readable.read_bytes()
                        ).hexdigest(),
                        "rules": [
                            {
                                "criterion_id": "location-approved",
                                "dimension": "location",
                                "classification": "hard_exclusion",
                                "operator": "one_of",
                                "values": ["Remote"],
                                "reason_code": "location_outside_approved_area",
                                "user_confirmed": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(CriteriaError, "user-confirmed"):
                load_search_criteria(structured, readable_path=readable)

    def test_loader_rejects_structured_criteria_when_readable_hash_has_drifted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            readable = root / "Search_Criteria.md"
            readable.write_text("# Changed criteria\n", encoding="utf-8")
            structured = root / "Search_Criteria.json"
            structured.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "readable_criteria_path": "Profile/Search_Criteria.md",
                        "readable_criteria_sha256": "c" * 64,
                        "rules": [],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(CriteriaError, "hash"):
                load_search_criteria(structured, readable_path=readable)

    def test_loader_rejects_a_binding_to_any_other_readable_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            readable = root / "Search_Criteria.md"
            readable.write_text("# Approved criteria\n", encoding="utf-8")
            structured = root / "Search_Criteria.json"
            structured.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "readable_criteria_path": "../Different_Criteria.md",
                        "readable_criteria_sha256": hashlib.sha256(
                            readable.read_bytes()
                        ).hexdigest(),
                        "rules": [],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(CriteriaError, "path"):
                load_search_criteria(structured, readable_path=readable)

    def test_unknown_hard_filter_evidence_is_not_a_confirmed_mismatch(self) -> None:
        rule = CriteriaRule(
            criterion_id="travel-limit",
            dimension="travel",
            classification="hard_exclusion",
            operator="maximum",
            values=("25",),
            reason_code="travel_above_approved_limit",
            user_confirmed=True,
        )

        outcome = evaluate_hard_filters(candidate(), criteria(rule))

        self.assertEqual(outcome.result, "unknown")
        self.assertEqual(outcome.decisions[0].result, "unknown")
        self.assertEqual(outcome.reason_codes, ())

    def test_confirmed_mismatch_skips_semantic_assessment(self) -> None:
        rule = CriteriaRule(
            criterion_id="location-approved",
            dimension="location",
            classification="hard_exclusion",
            operator="one_of",
            values=("New York", "Remote"),
            reason_code="location_outside_approved_area",
            user_confirmed=True,
        )
        calls: list[str] = []

        def semantic_assessor(_: CandidateJob) -> JobAssessment:
            calls.append("called")
            return JobAssessment("strong_match", "fit", (), (), ())

        result = filter_then_assess(
            candidate(location="Example City"), criteria(rule), semantic_assessor
        )

        self.assertEqual(result.filter_outcome.result, "confirmed_mismatch")
        self.assertIsNone(result.assessment)
        self.assertEqual(calls, [])

    def test_preferences_never_act_as_deterministic_hard_filters(self) -> None:
        rule = CriteriaRule(
            criterion_id="location-preference",
            dimension="location",
            classification="preference",
            operator="one_of",
            values=("New York",),
            reason_code="location_not_preferred",
            user_confirmed=False,
        )

        outcome = evaluate_hard_filters(
            candidate(location="Example City"), criteria(rule)
        )

        self.assertEqual(outcome.result, "pass")
        self.assertEqual(outcome.decisions, ())


if __name__ == "__main__":
    unittest.main()
