from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from career_pipeline.criteria import (
    ComparableThreshold,
    CriteriaError,
    CriteriaRule,
    NormalizedEvidence,
    SearchCriteria,
    evaluate_hard_filters,
    filter_then_assess,
    load_search_criteria,
)
from career_pipeline.evaluation import JobAssessment
from career_pipeline.sources.base import CandidateJob


def candidate(**changes: object) -> CandidateJob:
    base = CandidateJob(
        source="public-search", source_record_id="synthetic-criteria-1",
        requisition_id="SYN-CRITERIA-1", employer="Example Cooperative",
        title="Operations Lead", responsibilities=("Lead fictional operations.",),
        location="Remote", workplace_model="remote", travel=None,
        compensation_evidence=None,
        posting_url="https://jobs.example/postings/SYN-CRITERIA-1",
        application_url="https://jobs.example/apply/SYN-CRITERIA-1",
        team="Operations", posted_at=None, updated_at=None,
        deadline="2026-12-01", verified_at="2026-09-11T18:00:00Z",
        verification_status="verified", raw_field_hash="a" * 64,
        uncertainties=("travel", "compensation"),
    )
    return replace(base, **changes)


def criteria(*rules: CriteriaRule) -> SearchCriteria:
    return SearchCriteria("Profile/Search_Criteria.md", "b" * 64, rules)


def text_rule(**changes: object) -> CriteriaRule:
    base = CriteriaRule(
        criterion_id="location-approved", dimension="location",
        subject="job_location", classification="hard_exclusion",
        operator="one_of", reason_code="location_outside_approved_area",
        user_confirmed=True, values=("Remote",),
    )
    return replace(base, **changes)


def numeric_rule(**changes: object) -> CriteriaRule:
    base = CriteriaRule(
        criterion_id="minimum-compensation", dimension="compensation",
        subject="base_compensation", classification="hard_exclusion",
        operator="minimum", reason_code="compensation_below_minimum",
        user_confirmed=True,
        threshold=ComparableThreshold("150000", "money", "USD", "year"),
    )
    return replace(base, **changes)


def evidence(*, dimension: str, subject: str, lower: str, upper: str,
             unit: str, currency: str | None = None,
             pay_period: str | None = None, **changes: object) -> NormalizedEvidence:
    base = NormalizedEvidence(
        dimension=dimension, subject=subject, status="known",
        value_type="number", provenance="source_receipt", certainty="verified",
        source="public-search", source_record_id="synthetic-criteria-1",
        source_field_hash="a" * 64, lower_bound=lower, upper_bound=upper,
        unit=unit, currency=currency, pay_period=pay_period,
    )
    return replace(base, **changes)


class StructuredCriteriaTests(unittest.TestCase):
    def test_ambiguous_raw_numeric_source_text_stays_unknown(self) -> None:
        travel_rule = numeric_rule(
            criterion_id="maximum-travel", dimension="travel",
            subject="travel_percentage", operator="maximum",
            reason_code="travel_above_maximum",
            threshold=ComparableThreshold("25", "percent"),
        )
        cases = (
            (candidate(compensation_evidence="$180k per year"), numeric_rule()),
            (candidate(compensation_evidence="$100,000-$200,000 per year"), numeric_rule()),
            (candidate(compensation_evidence="EUR 180000 per year"), numeric_rule()),
            (candidate(compensation_evidence="$80 per hour"), numeric_rule()),
            (candidate(travel="10-50%"), travel_rule),
        )
        for job, rule in cases:
            with self.subTest(value=job.compensation_evidence or job.travel):
                self.assertEqual(evaluate_hard_filters(job, criteria(rule)).result, "unknown")

    def test_typed_numeric_bounds_only_confirm_nonoverlapping_results(self) -> None:
        for lower, upper, expected in (
            ("180000", "200000", "pass"),
            ("100000", "200000", "unknown"),
            ("100000", "149999", "confirmed_mismatch"),
        ):
            supplied = evidence(
                dimension="compensation", subject="base_compensation",
                lower=lower, upper=upper, unit="money", currency="USD",
                pay_period="year",
            )
            with self.subTest(lower=lower, upper=upper):
                self.assertEqual(
                    evaluate_hard_filters(candidate(), criteria(numeric_rule()), evidence=(supplied,)).result,
                    expected,
                )

    def test_incompatible_currency_or_pay_period_stays_unknown(self) -> None:
        for currency, period in (("EUR", "year"), ("USD", "hour")):
            supplied = evidence(
                dimension="compensation", subject="base_compensation",
                lower="180000", upper="180000", unit="money",
                currency=currency, pay_period=period,
            )
            self.assertEqual(
                evaluate_hard_filters(candidate(), criteria(numeric_rule()), evidence=(supplied,)).result,
                "unknown",
            )

    def test_required_start_date_does_not_use_application_deadline(self) -> None:
        start_rule = CriteriaRule(
            criterion_id="earliest-start-date", dimension="timing",
            subject="required_start_date", classification="hard_exclusion",
            operator="on_or_after", reason_code="required_start_before_availability",
            user_confirmed=True, threshold=ComparableThreshold("2027-01-05"),
        )
        deadline_rule = replace(
            start_rule, criterion_id="application-window",
            subject="application_deadline", operator="on_or_before",
            reason_code="application_deadline_too_late",
            threshold=ComparableThreshold("2026-12-31"),
        )
        self.assertEqual(evaluate_hard_filters(candidate(), criteria(start_rule)).result, "unknown")
        self.assertEqual(evaluate_hard_filters(candidate(), criteria(deadline_rule)).result, "pass")

    def test_untrusted_or_conflicting_override_cannot_replace_verified_source_fact(self) -> None:
        malformed = {"dimension": "location", "status": "unknown"}
        conflicting = NormalizedEvidence(
            dimension="location", subject="job_location", status="known",
            value_type="text", provenance="source_receipt", certainty="verified",
            source="public-search", source_record_id="synthetic-criteria-1",
            source_field_hash="a" * 64, text_value="Chicago",
        )
        unsupported = replace(conflicting, certainty="unverified", text_value="Remote")
        self.assertEqual(evaluate_hard_filters(candidate(), criteria(text_rule()), evidence=(malformed,)).result, "pass")
        self.assertEqual(evaluate_hard_filters(candidate(), criteria(text_rule()), evidence=(conflicting,)).result, "unknown")
        self.assertEqual(evaluate_hard_filters(candidate(), criteria(text_rule()), evidence=(unsupported,)).result, "pass")

    def test_oversized_normalized_text_is_ignored_as_malformed(self) -> None:
        oversized = NormalizedEvidence(
            dimension="location", subject="job_location", status="known",
            value_type="text", provenance="source_receipt", certainty="verified",
            source="public-search", source_record_id="synthetic-criteria-1",
            source_field_hash="a" * 64, text_value="Remote" + "x" * 400,
        )
        self.assertEqual(
            evaluate_hard_filters(
                candidate(location=None), criteria(text_rule()), evidence=(oversized,)
            ).result,
            "unknown",
        )

    def test_literal_unknown_source_text_is_unknown(self) -> None:
        self.assertEqual(evaluate_hard_filters(candidate(location="Unknown"), criteria(text_rule())).result, "unknown")

    def test_confirmed_mismatch_skips_semantic_assessment(self) -> None:
        calls: list[str] = []
        def semantic_assessor(_: CandidateJob) -> JobAssessment:
            calls.append("called")
            return JobAssessment("strong_match", "fit", (), (), ())
        result = filter_then_assess(candidate(location="Example City"), criteria(text_rule()), semantic_assessor)
        self.assertEqual(result.filter_outcome.result, "confirmed_mismatch")
        self.assertIsNone(result.assessment)
        self.assertEqual(calls, [])

    def test_preferences_never_act_as_hard_filters(self) -> None:
        outcome = evaluate_hard_filters(
            candidate(location="Example City"),
            criteria(text_rule(classification="preference", user_confirmed=False)),
        )
        self.assertEqual(outcome.result, "pass")
        self.assertEqual(outcome.decisions, ())

    def test_constructed_rules_use_the_same_strict_validator(self) -> None:
        invalid_rules = (
            text_rule(user_confirmed="false"),
            text_rule(reason_code="Private personal rationale"),
            text_rule(operator="maximum"),
            text_rule(values=("",)),
            numeric_rule(threshold=ComparableThreshold("many", "money", "USD", "year")),
            numeric_rule(threshold=ComparableThreshold("-1", "money", "USD", "year")),
            numeric_rule(
                criterion_id="maximum-travel", dimension="travel",
                subject="travel_percentage", operator="maximum",
                reason_code="travel_above_maximum",
                threshold=ComparableThreshold("101", "percent"),
            ),
            numeric_rule(values=("ignored",)),
        )
        for rule in invalid_rules:
            with self.subTest(rule=rule):
                with self.assertRaises(CriteriaError):
                    evaluate_hard_filters(candidate(), criteria(rule))

    def test_loader_rejects_coercions_extras_duplicates_and_invalid_arity(self) -> None:
        readable_text = "# Approved criteria\n"
        readable_hash = hashlib.sha256(readable_text.encode()).hexdigest()
        valid_rule = {
            "criterion_id": "location-approved", "dimension": "location",
            "subject": "job_location", "classification": "hard_exclusion",
            "operator": "one_of", "values": ["Remote"],
            "reason_code": "location_outside_approved_area", "user_confirmed": True,
        }
        base = {"schema_version": 1, "readable_criteria_path": "Profile/Search_Criteria.md", "readable_criteria_sha256": readable_hash}
        invalid_documents = (
            {**base, "schema_version": True, "rules": []},
            {**base, "rules": [valid_rule], "extra": 1},
            {**base, "rules": [{**valid_rule, "criterion_id": 23}]},
            {**base, "rules": [{**valid_rule, "values": [None]}]},
            {**base, "rules": [valid_rule, valid_rule]},
            {**base, "rules": [{**valid_rule, "operator": "equals", "values": ["Remote", "Hybrid"]}]},
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            readable = root / "Search_Criteria.md"
            readable.write_text(readable_text, encoding="utf-8")
            structured = root / "Search_Criteria.json"
            for document in invalid_documents:
                with self.subTest(document=document):
                    structured.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaises(CriteriaError):
                        load_search_criteria(structured, readable_path=readable)

    def test_structured_hash_changes_with_rule_threshold(self) -> None:
        first = criteria(numeric_rule())
        second = criteria(numeric_rule(threshold=ComparableThreshold("160000", "money", "USD", "year")))
        self.assertNotEqual(first.structured_sha256, second.structured_sha256)


if __name__ == "__main__":
    unittest.main()
