"""Structured, user-owned search criteria and deterministic hard filters."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .evaluation import JobAssessment
from .sources.base import CandidateJob


class CriteriaError(ValueError):
    pass


@dataclass(frozen=True)
class CriteriaRule:
    criterion_id: str
    dimension: str
    classification: str
    operator: str
    values: tuple[str, ...]
    reason_code: str
    user_confirmed: bool


@dataclass(frozen=True)
class SearchCriteria:
    readable_criteria_path: str
    readable_criteria_sha256: str
    rules: tuple[CriteriaRule, ...]
    schema_version: int = 1


@dataclass(frozen=True)
class FilterDecision:
    criterion_id: str
    dimension: str
    result: str
    reason_code: str


@dataclass(frozen=True)
class HardFilterOutcome:
    result: str
    decisions: tuple[FilterDecision, ...]

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                decision.reason_code
                for decision in self.decisions
                if decision.result == "confirmed_mismatch"
            )
        )


@dataclass(frozen=True)
class FilteredAssessment:
    filter_outcome: HardFilterOutcome
    assessment: JobAssessment | None


def load_search_criteria(
    path: Path,
    *,
    readable_path: Path | None = None,
) -> SearchCriteria:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CriteriaError("structured search criteria could not be read") from exc
    if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
        raise CriteriaError("structured search criteria schema version must equal 1")
    readable_relative = raw.get("readable_criteria_path")
    readable_hash = raw.get("readable_criteria_sha256")
    rules_raw = raw.get("rules")
    if readable_relative != "Profile/Search_Criteria.md":
        raise CriteriaError("readable criteria path must be Profile/Search_Criteria.md")
    if not isinstance(readable_hash, str) or re.fullmatch(r"[0-9a-f]{64}", readable_hash) is None:
        raise CriteriaError("readable criteria hash must be a SHA-256 hash")
    if not isinstance(rules_raw, Sequence) or isinstance(rules_raw, (str, bytes)):
        raise CriteriaError("structured search criteria rules must be an array")
    rules: list[CriteriaRule] = []
    for index, item in enumerate(rules_raw):
        if not isinstance(item, Mapping):
            raise CriteriaError(f"criteria rule {index} must be an object")
        values = item.get("values")
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise CriteriaError(f"criteria rule {index} values must be an array")
        rule = CriteriaRule(
            criterion_id=str(item.get("criterion_id") or ""),
            dimension=str(item.get("dimension") or ""),
            classification=str(item.get("classification") or ""),
            operator=str(item.get("operator") or ""),
            values=tuple(str(value) for value in values),
            reason_code=str(item.get("reason_code") or ""),
            user_confirmed=item.get("user_confirmed") is True,
        )
        _validate_rule(rule, index)
        rules.append(rule)
    criteria = SearchCriteria(
        readable_criteria_path=readable_relative,
        readable_criteria_sha256=readable_hash,
        rules=tuple(rules),
    )
    if readable_path is not None:
        try:
            actual_hash = hashlib.sha256(readable_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise CriteriaError("readable search criteria could not be read") from exc
        if actual_hash != criteria.readable_criteria_sha256:
            raise CriteriaError("structured criteria hash does not match readable criteria")
    return criteria


def evaluate_hard_filters(
    candidate: CandidateJob,
    criteria: SearchCriteria,
    *,
    evidence: Mapping[str, object] | None = None,
) -> HardFilterOutcome:
    decisions: list[FilterDecision] = []
    supplied = evidence or {}
    for rule in criteria.rules:
        if rule.classification != "hard_exclusion":
            continue
        _validate_rule(rule, len(decisions))
        observed = (
            supplied[rule.dimension]
            if rule.dimension in supplied
            else _candidate_evidence(candidate, rule.dimension)
        )
        if _is_unknown(observed):
            result = "unknown"
        else:
            matched = _matches(observed, rule.operator, rule.values)
            result = "pass" if matched is True else (
                "confirmed_mismatch" if matched is False else "unknown"
            )
        decisions.append(
            FilterDecision(
                criterion_id=rule.criterion_id,
                dimension=rule.dimension,
                result=result,
                reason_code=rule.reason_code,
            )
        )
    results = {decision.result for decision in decisions}
    overall = (
        "confirmed_mismatch"
        if "confirmed_mismatch" in results
        else "unknown" if "unknown" in results else "pass"
    )
    return HardFilterOutcome(result=overall, decisions=tuple(decisions))


def filter_then_assess(
    candidate: CandidateJob,
    criteria: SearchCriteria,
    semantic_assessor: Callable[[CandidateJob], JobAssessment],
    *,
    evidence: Mapping[str, object] | None = None,
) -> FilteredAssessment:
    outcome = evaluate_hard_filters(candidate, criteria, evidence=evidence)
    if outcome.result == "confirmed_mismatch":
        return FilteredAssessment(outcome, None)
    return FilteredAssessment(outcome, semantic_assessor(candidate))


_DIMENSIONS = {
    "compensation",
    "location",
    "work_authorization",
    "travel",
    "timing",
    "role",
    "workplace",
}
_CLASSIFICATIONS = {"hard_exclusion", "preference", "unknown_tolerant"}
_OPERATORS = {
    "equals",
    "one_of",
    "contains_any",
    "minimum",
    "maximum",
    "on_or_after",
    "on_or_before",
}
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _validate_rule(rule: CriteriaRule, index: int) -> None:
    if not rule.criterion_id or not rule.reason_code:
        raise CriteriaError(f"criteria rule {index} needs an id and reason code")
    if rule.dimension not in _DIMENSIONS:
        raise CriteriaError(f"criteria rule {index} has an unsupported dimension")
    if rule.classification not in _CLASSIFICATIONS:
        raise CriteriaError(f"criteria rule {index} has an unsupported classification")
    if rule.operator not in _OPERATORS or not rule.values:
        raise CriteriaError(f"criteria rule {index} has an unsupported condition")
    if rule.classification == "hard_exclusion" and not rule.user_confirmed:
        raise CriteriaError(f"hard exclusion {rule.criterion_id} must be user-confirmed")


def _candidate_evidence(candidate: CandidateJob, dimension: str) -> object:
    return {
        "compensation": candidate.compensation_evidence,
        "location": candidate.location,
        "work_authorization": None,
        "travel": candidate.travel,
        "timing": candidate.deadline,
        "role": candidate.title,
        "workplace": candidate.workplace_model,
    }[dimension]


def _is_unknown(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return not value
    return False


def _normalized(value: object) -> str:
    return " ".join(str(value).casefold().split())


def _matches(observed: object, operator: str, values: tuple[str, ...]) -> bool | None:
    observed_values = (
        tuple(observed)
        if isinstance(observed, Sequence) and not isinstance(observed, (str, bytes))
        else (observed,)
    )
    normalized_observed = tuple(_normalized(value) for value in observed_values)
    normalized_rules = tuple(_normalized(value) for value in values)
    if operator == "equals":
        return normalized_observed[0] == normalized_rules[0]
    if operator == "one_of":
        return any(value in normalized_rules for value in normalized_observed)
    if operator == "contains_any":
        return any(
            expected in actual
            for actual in normalized_observed
            for expected in normalized_rules
        )
    if operator in {"minimum", "maximum"}:
        observed_number = _first_number(str(observed_values[0]))
        required_number = _first_number(values[0])
        if observed_number is None or required_number is None:
            return None
        return (
            observed_number >= required_number
            if operator == "minimum"
            else observed_number <= required_number
        )
    if operator in {"on_or_after", "on_or_before"}:
        try:
            observed_date = date.fromisoformat(str(observed_values[0]))
            required_date = date.fromisoformat(values[0])
        except ValueError:
            return None
        return (
            observed_date >= required_date
            if operator == "on_or_after"
            else observed_date <= required_date
        )
    return None


def _first_number(value: str) -> float | None:
    found = _NUMBER.search(value)
    if found is None:
        return None
    return float(found.group(0).replace(",", ""))
