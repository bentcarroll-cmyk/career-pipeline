"""Strict structured search criteria and source-bound normalized evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .atomic import atomic_write_json, load_json
from .contracts import WorkspacePaths
from .evaluation import JobAssessment
from .onboarding import load_onboarding_state
from .sources.base import CandidateJob


class CriteriaError(ValueError):
    pass


@dataclass(frozen=True)
class ComparableThreshold:
    value: str
    unit: str | None = None
    currency: str | None = None
    pay_period: str | None = None


@dataclass(frozen=True)
class CriteriaRule:
    criterion_id: str
    dimension: str
    subject: str
    classification: str
    operator: str
    reason_code: str
    user_confirmed: bool
    values: tuple[str, ...] = ()
    threshold: ComparableThreshold | None = None


@dataclass(frozen=True)
class SearchCriteria:
    readable_criteria_path: str
    readable_criteria_sha256: str
    rules: tuple[CriteriaRule, ...]
    schema_version: int = 1

    @property
    def structured_sha256(self) -> str:
        validate_search_criteria(self)
        return _hash_mapping(criteria_to_mapping(self))


@dataclass(frozen=True)
class NormalizedEvidence:
    dimension: str
    subject: str
    status: str
    value_type: str
    provenance: str
    certainty: str
    source: str
    source_record_id: str
    source_field_hash: str
    text_value: str | None = None
    lower_bound: str | None = None
    upper_bound: str | None = None
    unit: str | None = None
    currency: str | None = None
    pay_period: str | None = None


@dataclass(frozen=True)
class FilterDecision:
    criterion_id: str
    dimension: str
    subject: str
    result: str
    reason_code: str
    rule_hash: str
    evidence_hash: str


@dataclass(frozen=True)
class HardFilterOutcome:
    result: str
    decisions: tuple[FilterDecision, ...]
    normalized_evidence: tuple[NormalizedEvidence, ...] = ()

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            decision.reason_code for decision in self.decisions
            if decision.result == "confirmed_mismatch"
        ))


@dataclass(frozen=True)
class FilteredAssessment:
    filter_outcome: HardFilterOutcome
    assessment: JobAssessment | None


_ROOT_KEYS = {"schema_version", "readable_criteria_path", "readable_criteria_sha256", "rules"}
_COMMON_RULE_KEYS = {
    "criterion_id", "dimension", "subject", "classification", "operator",
    "reason_code", "user_confirmed",
}
_CODE = re.compile(r"[a-z][a-z0-9-]{2,63}")
_REASON = re.compile(r"[a-z][a-z0-9_]{2,63}")
_HASH = re.compile(r"[0-9a-f]{64}")
_UNKNOWN_TEXT = {"unknown", "not stated", "unspecified", "n/a", "tbd", "to be determined"}
_CLASSIFICATIONS = {"hard_exclusion", "preference", "unknown_tolerant"}
_TEXT_RULES = {
    "location": {"job_location"},
    "work_authorization": {"required_authorization"},
    "role": {"job_title"},
    "workplace": {"workplace_model"},
}
_NUMBER_RULES = {
    "compensation": {"base_compensation"},
    "travel": {"travel_percentage"},
}
_DATE_RULES = {"timing": {"application_deadline", "required_start_date"}}
_TEXT_OPERATORS = {"equals", "one_of", "contains_any"}
_NUMBER_OPERATORS = {"minimum", "maximum"}
_DATE_OPERATORS = {"on_or_after", "on_or_before"}
_EVIDENCE_KEYS = {
    "dimension", "subject", "status", "value_type", "provenance", "certainty",
    "source", "source_record_id", "source_field_hash", "text_value", "lower_bound",
    "upper_bound", "unit", "currency", "pay_period",
}


def criteria_to_mapping(criteria: SearchCriteria) -> dict[str, object]:
    rules: list[dict[str, object]] = []
    for rule in criteria.rules:
        item: dict[str, object] = {
            "criterion_id": rule.criterion_id,
            "dimension": rule.dimension,
            "subject": rule.subject,
            "classification": rule.classification,
            "operator": rule.operator,
            "reason_code": rule.reason_code,
            "user_confirmed": rule.user_confirmed,
        }
        if rule.operator in _TEXT_OPERATORS:
            item["values"] = list(rule.values)
        elif rule.threshold is not None:
            threshold = {"value": rule.threshold.value}
            if rule.threshold.unit is not None:
                threshold["unit"] = rule.threshold.unit
            if rule.threshold.currency is not None:
                threshold["currency"] = rule.threshold.currency
            if rule.threshold.pay_period is not None:
                threshold["pay_period"] = rule.threshold.pay_period
            item["threshold"] = threshold
        rules.append(item)
    return {
        "schema_version": criteria.schema_version,
        "readable_criteria_path": criteria.readable_criteria_path,
        "readable_criteria_sha256": criteria.readable_criteria_sha256,
        "rules": rules,
    }


def validate_search_criteria(criteria: SearchCriteria) -> None:
    if type(criteria.schema_version) is not int or criteria.schema_version != 1:
        raise CriteriaError("structured search criteria schema version must equal 1")
    if criteria.readable_criteria_path != "Profile/Search_Criteria.md":
        raise CriteriaError("readable criteria path must be Profile/Search_Criteria.md")
    if type(criteria.readable_criteria_sha256) is not str or _HASH.fullmatch(criteria.readable_criteria_sha256) is None:
        raise CriteriaError("readable criteria hash must be a SHA-256 hash")
    if type(criteria.rules) is not tuple:
        raise CriteriaError("structured search criteria rules must be a tuple")
    seen: set[str] = set()
    for index, rule in enumerate(criteria.rules):
        _validate_rule(rule, index)
        if rule.criterion_id in seen:
            raise CriteriaError("criteria rule identifiers must be unique")
        seen.add(rule.criterion_id)


def load_search_criteria(path: Path, *, readable_path: Path) -> SearchCriteria:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CriteriaError("structured search criteria could not be read") from exc
    if type(raw) is not dict or set(raw) != _ROOT_KEYS:
        raise CriteriaError("structured search criteria fields are invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise CriteriaError("structured search criteria schema version must equal 1")
    if type(raw["rules"]) is not list:
        raise CriteriaError("structured search criteria rules must be an array")
    rules = tuple(_rule_from_mapping(item, index) for index, item in enumerate(raw["rules"]))
    criteria = SearchCriteria(
        readable_criteria_path=raw["readable_criteria_path"],
        readable_criteria_sha256=raw["readable_criteria_sha256"],
        rules=rules,
    )
    validate_search_criteria(criteria)
    try:
        actual_hash = hashlib.sha256(readable_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise CriteriaError("readable search criteria could not be read") from exc
    if actual_hash != criteria.readable_criteria_sha256:
        raise CriteriaError("structured criteria hash does not match readable criteria")
    return criteria


def resolve_workspace_criteria(
    workspace: WorkspacePaths,
    supplied: SearchCriteria | None = None,
) -> SearchCriteria | None:
    """Resolve current structured criteria and verify both persisted approvals."""
    structured_path = workspace.profile / "Search_Criteria.json"
    if structured_path.is_symlink():
        raise CriteriaError("structured search criteria must be a regular workspace file")
    if not structured_path.exists():
        if supplied is not None:
            raise CriteriaError("supplied criteria has no workspace structured document")
        return None
    if not structured_path.is_file():
        raise CriteriaError("structured search criteria is not a file")
    readable_path = workspace.profile / "Search_Criteria.md"
    if readable_path.is_symlink() or not readable_path.is_file():
        raise CriteriaError("readable search criteria must be a regular workspace file")
    current = load_search_criteria(structured_path, readable_path=readable_path)
    onboarding_path = workspace.state / "onboarding-state.json"
    approval_path = workspace.state / "search-criteria-approval.json"
    if onboarding_path.is_symlink() or approval_path.is_symlink():
        raise CriteriaError("structured search criteria approval must be a regular workspace file")
    try:
        onboarding = load_onboarding_state(onboarding_path)
        approval = load_json(approval_path)
    except (OSError, ValueError) as exc:
        raise CriteriaError("structured search criteria approval is missing or invalid") from exc
    expected_approval = {
        "schema_version": 1,
        "readable_criteria_sha256": current.readable_criteria_sha256,
        "structured_criteria_sha256": current.structured_sha256,
    }
    if onboarding.criteria_hash != current.readable_criteria_sha256 or approval != expected_approval:
        raise CriteriaError("structured search criteria is not currently approved")
    if supplied is not None:
        validate_search_criteria(supplied)
        if supplied.structured_sha256 != current.structured_sha256:
            raise CriteriaError("supplied search criteria is stale")
    return current


def approve_workspace_criteria(workspace: WorkspacePaths) -> dict[str, object]:
    """Persist approval for the current readable and structured criteria pair.

    Callers invoke this only after the user has reviewed and explicitly approved
    both files. The onboarding state must already identify the current readable
    document, so this helper cannot approve drifted content.
    """
    structured_path = workspace.profile / "Search_Criteria.json"
    readable_path = workspace.profile / "Search_Criteria.md"
    if (
        structured_path.is_symlink()
        or readable_path.is_symlink()
        or not structured_path.is_file()
        or not readable_path.is_file()
    ):
        raise CriteriaError("current readable and structured criteria are required")
    current = load_search_criteria(structured_path, readable_path=readable_path)
    try:
        onboarding = load_onboarding_state(workspace.state / "onboarding-state.json")
    except (OSError, ValueError) as exc:
        raise CriteriaError("readable search criteria approval is missing or invalid") from exc
    if onboarding.criteria_hash != current.readable_criteria_sha256:
        raise CriteriaError("readable search criteria is not currently approved")
    approval: dict[str, object] = {
        "schema_version": 1,
        "readable_criteria_sha256": current.readable_criteria_sha256,
        "structured_criteria_sha256": current.structured_sha256,
    }
    atomic_write_json(workspace.state / "search-criteria-approval.json", approval)
    return approval


def evaluate_hard_filters(
    candidate: CandidateJob,
    criteria: SearchCriteria,
    *,
    evidence: object = (),
) -> HardFilterOutcome:
    validate_search_criteria(criteria)
    supplied = _validated_evidence(candidate, evidence)
    decisions: list[FilterDecision] = []
    used: list[NormalizedEvidence] = []
    for rule in criteria.rules:
        if rule.classification != "hard_exclusion":
            continue
        source_value = _candidate_evidence(candidate, rule.dimension, rule.subject)
        supplied_value = supplied.get((rule.dimension, rule.subject))
        observed = _select_evidence(source_value, supplied_value)
        result = _evaluate_rule(rule, observed)
        used.append(observed)
        decisions.append(FilterDecision(
            criterion_id=rule.criterion_id,
            dimension=rule.dimension,
            subject=rule.subject,
            result=result,
            reason_code=rule.reason_code,
            rule_hash=_hash_mapping(_rule_mapping(rule)),
            evidence_hash=_hash_mapping(evidence_to_mapping(observed)),
        ))
    results = {item.result for item in decisions}
    overall = "confirmed_mismatch" if "confirmed_mismatch" in results else (
        "unknown" if "unknown" in results else "pass"
    )
    return HardFilterOutcome(overall, tuple(decisions), tuple(used))


def filter_then_assess(
    candidate: CandidateJob,
    criteria: SearchCriteria,
    semantic_assessor: Callable[[CandidateJob], JobAssessment],
    *,
    evidence: object = (),
) -> FilteredAssessment:
    outcome = evaluate_hard_filters(candidate, criteria, evidence=evidence)
    if outcome.result == "confirmed_mismatch":
        return FilteredAssessment(outcome, None)
    return FilteredAssessment(outcome, semantic_assessor(candidate))


def evidence_to_mapping(value: NormalizedEvidence) -> dict[str, object]:
    return {key: item for key, item in asdict(value).items() if item is not None}


def _rule_from_mapping(raw: object, index: int) -> CriteriaRule:
    if type(raw) is not dict:
        raise CriteriaError(f"criteria rule {index} must be an object")
    operator = raw.get("operator")
    expected = _COMMON_RULE_KEYS | ({"values"} if operator in _TEXT_OPERATORS else {"threshold"})
    if set(raw) != expected:
        raise CriteriaError(f"criteria rule {index} fields are invalid")
    common_names = ("criterion_id", "dimension", "subject", "classification", "operator", "reason_code")
    if any(type(raw.get(name)) is not str for name in common_names) or type(raw.get("user_confirmed")) is not bool:
        raise CriteriaError(f"criteria rule {index} field types are invalid")
    values: tuple[str, ...] = ()
    threshold = None
    if operator in _TEXT_OPERATORS:
        raw_values = raw["values"]
        if type(raw_values) is not list or any(type(value) is not str for value in raw_values):
            raise CriteriaError(f"criteria rule {index} values are invalid")
        values = tuple(raw_values)
    else:
        threshold = _threshold_from_mapping(raw["threshold"], raw["dimension"], index)
    rule = CriteriaRule(
        criterion_id=raw["criterion_id"], dimension=raw["dimension"],
        subject=raw["subject"], classification=raw["classification"],
        operator=raw["operator"], reason_code=raw["reason_code"],
        user_confirmed=raw["user_confirmed"], values=values, threshold=threshold,
    )
    _validate_rule(rule, index)
    return rule


def _threshold_from_mapping(raw: object, dimension: object, index: int) -> ComparableThreshold:
    if type(raw) is not dict:
        raise CriteriaError(f"criteria rule {index} threshold is invalid")
    expected = {"value"}
    if dimension == "travel":
        expected |= {"unit"}
    elif dimension == "compensation":
        expected |= {"unit", "currency", "pay_period"}
    if set(raw) != expected or any(type(value) is not str for value in raw.values()):
        raise CriteriaError(f"criteria rule {index} threshold is invalid")
    return ComparableThreshold(
        value=raw["value"], unit=raw.get("unit"), currency=raw.get("currency"),
        pay_period=raw.get("pay_period"),
    )


def _validate_rule(rule: CriteriaRule, index: int) -> None:
    if not isinstance(rule, CriteriaRule):
        raise CriteriaError(f"criteria rule {index} is invalid")
    if type(rule.criterion_id) is not str or _CODE.fullmatch(rule.criterion_id) is None:
        raise CriteriaError(f"criteria rule {index} identifier is invalid")
    if type(rule.reason_code) is not str or _REASON.fullmatch(rule.reason_code) is None:
        raise CriteriaError(f"criteria rule {index} reason code is invalid")
    if type(rule.classification) is not str or rule.classification not in _CLASSIFICATIONS:
        raise CriteriaError(f"criteria rule {index} classification is invalid")
    if any(type(value) is not str for value in (rule.dimension, rule.subject, rule.operator)):
        raise CriteriaError(f"criteria rule {index} field types are invalid")
    if type(rule.user_confirmed) is not bool:
        raise CriteriaError(f"criteria rule {index} confirmation must be a boolean")
    if rule.classification == "hard_exclusion" and rule.user_confirmed is not True:
        raise CriteriaError(f"hard exclusion {rule.criterion_id} must be user-confirmed")
    if type(rule.values) is not tuple:
        raise CriteriaError(f"criteria rule {index} values must be a tuple")
    allowed_subjects = (_TEXT_RULES | _NUMBER_RULES | _DATE_RULES).get(rule.dimension)
    if allowed_subjects is None or rule.subject not in allowed_subjects:
        raise CriteriaError(f"criteria rule {index} dimension and subject are incompatible")
    if rule.dimension in _TEXT_RULES:
        if rule.operator not in _TEXT_OPERATORS or rule.threshold is not None:
            raise CriteriaError(f"criteria rule {index} operator is incompatible")
        if type(rule.values) is not tuple or not rule.values or any(
            type(value) is not str or not value.strip() or len(value) > 160 for value in rule.values
        ) or len(set(rule.values)) != len(rule.values):
            raise CriteriaError(f"criteria rule {index} values are invalid")
        if rule.operator == "equals" and len(rule.values) != 1:
            raise CriteriaError(f"criteria rule {index} equals needs one value")
        return
    if rule.values or rule.threshold is None or not isinstance(rule.threshold, ComparableThreshold):
        raise CriteriaError(f"criteria rule {index} threshold is required")
    if rule.dimension in _NUMBER_RULES:
        threshold_value = _decimal(rule.threshold.value)
        if (
            rule.operator not in _NUMBER_OPERATORS
            or threshold_value is None
            or threshold_value < 0
            or (rule.dimension == "travel" and threshold_value > 100)
        ):
            raise CriteriaError(f"criteria rule {index} numeric threshold is invalid")
        if rule.dimension == "travel" and (
            rule.threshold.unit != "percent" or rule.threshold.currency is not None
            or rule.threshold.pay_period is not None
        ):
            raise CriteriaError(f"criteria rule {index} travel units are invalid")
        if rule.dimension == "compensation" and (
            rule.threshold.unit != "money" or rule.threshold.currency not in {"USD", "EUR", "GBP", "CAD"}
            or rule.threshold.pay_period not in {"year", "month", "week", "hour"}
        ):
            raise CriteriaError(f"criteria rule {index} compensation units are invalid")
        return
    if rule.operator not in _DATE_OPERATORS or set(asdict(rule.threshold)) - {"value"} != {"unit", "currency", "pay_period"}:
        raise CriteriaError(f"criteria rule {index} date threshold is invalid")
    if any((rule.threshold.unit, rule.threshold.currency, rule.threshold.pay_period)):
        raise CriteriaError(f"criteria rule {index} date units are invalid")
    try:
        date.fromisoformat(rule.threshold.value)
    except (TypeError, ValueError) as exc:
        raise CriteriaError(f"criteria rule {index} date threshold is invalid") from exc


def _candidate_evidence(candidate: CandidateJob, dimension: str, subject: str) -> NormalizedEvidence:
    common = dict(
        dimension=dimension, subject=subject, provenance="normalized_candidate",
        certainty="verified" if candidate.verification_status == "verified" else "unverified",
        source=candidate.source, source_record_id=candidate.source_record_id,
        source_field_hash=candidate.raw_field_hash,
    )
    text = None
    if (dimension, subject) == ("location", "job_location"):
        text = candidate.location
    elif (dimension, subject) == ("workplace", "workplace_model"):
        text = candidate.workplace_model
    elif (dimension, subject) == ("role", "job_title"):
        text = candidate.title
    if text is not None:
        cleaned = " ".join(text.split())
        if (
            cleaned.casefold() not in _UNKNOWN_TEXT
            and len(cleaned) <= 280
            and common["certainty"] == "verified"
        ):
            return NormalizedEvidence(**common, status="known", value_type="text", text_value=cleaned)
    if (dimension, subject) == ("timing", "application_deadline") and candidate.deadline and common["certainty"] == "verified":
        try:
            date.fromisoformat(candidate.deadline)
        except ValueError:
            pass
        else:
            return NormalizedEvidence(
                **common, status="known", value_type="date",
                lower_bound=candidate.deadline, upper_bound=candidate.deadline,
            )
    value_type = "number" if dimension in _NUMBER_RULES else (
        "date" if dimension in _DATE_RULES else "text"
    )
    return NormalizedEvidence(**common, status="unknown", value_type=value_type)


def _validated_evidence(candidate: CandidateJob, raw: object) -> dict[tuple[str, str], NormalizedEvidence]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return {}
    grouped: dict[tuple[str, str], list[NormalizedEvidence]] = {}
    for item in raw:
        parsed = item if isinstance(item, NormalizedEvidence) else _evidence_from_mapping(item)
        if parsed is None or not _valid_evidence(parsed, candidate) or parsed.status != "known":
            continue
        grouped.setdefault((parsed.dimension, parsed.subject), []).append(parsed)
    result: dict[tuple[str, str], NormalizedEvidence] = {}
    for key, items in grouped.items():
        first = items[0]
        if all(evidence_to_mapping(item) == evidence_to_mapping(first) for item in items[1:]):
            result[key] = first
    return result


def _evidence_from_mapping(raw: object) -> NormalizedEvidence | None:
    if type(raw) is not dict or not set(raw).issubset(_EVIDENCE_KEYS):
        return None
    required = {"dimension", "subject", "status", "value_type", "provenance", "certainty", "source", "source_record_id", "source_field_hash"}
    if not required.issubset(raw) or any(type(raw[name]) is not str for name in raw):
        return None
    try:
        return NormalizedEvidence(**raw)
    except TypeError:
        return None


def _valid_evidence(value: NormalizedEvidence, candidate: CandidateJob) -> bool:
    if value.provenance != "source_receipt" or value.certainty != "verified" or value.status not in {"known", "unknown", "conflicting"}:
        return False
    if (value.source, value.source_record_id, value.source_field_hash) != (
        candidate.source, candidate.source_record_id, candidate.raw_field_hash
    ) or _HASH.fullmatch(value.source_field_hash or "") is None:
        return False
    allowed = (_TEXT_RULES | _NUMBER_RULES | _DATE_RULES).get(value.dimension, set())
    if value.subject not in allowed:
        return False
    if value.status != "known":
        return True
    if value.dimension in _TEXT_RULES:
        return value.value_type == "text" and isinstance(value.text_value, str) and 0 < len(value.text_value.strip()) <= 280 and not any(
            (value.lower_bound, value.upper_bound, value.unit, value.currency, value.pay_period)
        )
    if value.dimension in _NUMBER_RULES:
        if value.value_type != "number" or _decimal(value.lower_bound) is None or _decimal(value.upper_bound) is None:
            return False
        lower = _decimal(value.lower_bound)
        upper = _decimal(value.upper_bound)
        if lower > upper or lower < 0 or (value.dimension == "travel" and upper > 100):
            return False
        if value.dimension == "travel":
            return value.unit == "percent" and value.currency is None and value.pay_period is None
        return value.unit == "money" and value.currency in {"USD", "EUR", "GBP", "CAD"} and value.pay_period in {"year", "month", "week", "hour"}
    if value.value_type != "date" or any((value.text_value, value.unit, value.currency, value.pay_period)):
        return False
    try:
        return date.fromisoformat(value.lower_bound or "") <= date.fromisoformat(value.upper_bound or "")
    except ValueError:
        return False


def _select_evidence(source: NormalizedEvidence, supplied: NormalizedEvidence | None) -> NormalizedEvidence:
    if supplied is None:
        return source
    if source.status != "known":
        return supplied
    if _comparable_value(source) == _comparable_value(supplied):
        return source
    return NormalizedEvidence(
        dimension=source.dimension, subject=source.subject, status="conflicting",
        value_type=source.value_type, provenance="normalized_candidate", certainty="verified",
        source=source.source, source_record_id=source.source_record_id,
        source_field_hash=source.source_field_hash,
    )


def _comparable_value(value: NormalizedEvidence) -> tuple[object, ...]:
    return (value.value_type, value.text_value, value.lower_bound, value.upper_bound, value.unit, value.currency, value.pay_period)


def _evaluate_rule(rule: CriteriaRule, evidence: NormalizedEvidence) -> str:
    if evidence.status != "known":
        return "unknown"
    if rule.dimension in _TEXT_RULES:
        actual = " ".join((evidence.text_value or "").casefold().split())
        expected = tuple(" ".join(value.casefold().split()) for value in rule.values)
        matched = actual == expected[0] if rule.operator == "equals" else (
            actual in expected if rule.operator == "one_of" else any(value in actual for value in expected)
        )
        return "pass" if matched else "confirmed_mismatch"
    threshold = rule.threshold
    assert threshold is not None
    if rule.dimension in _NUMBER_RULES:
        if (evidence.unit, evidence.currency, evidence.pay_period) != (
            threshold.unit, threshold.currency, threshold.pay_period
        ):
            return "unknown"
        lower, upper, target = _decimal(evidence.lower_bound), _decimal(evidence.upper_bound), _decimal(threshold.value)
    else:
        try:
            lower, upper, target = (
                date.fromisoformat(evidence.lower_bound or ""),
                date.fromisoformat(evidence.upper_bound or ""),
                date.fromisoformat(threshold.value),
            )
        except ValueError:
            return "unknown"
    if lower is None or upper is None or target is None:
        return "unknown"
    minimum = rule.operator in {"minimum", "on_or_after"}
    if minimum:
        return "pass" if lower >= target else ("confirmed_mismatch" if upper < target else "unknown")
    return "pass" if upper <= target else ("confirmed_mismatch" if lower > target else "unknown")


def _decimal(value: object) -> Decimal | None:
    if type(value) is not str or not value or not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _rule_mapping(rule: CriteriaRule) -> dict[str, object]:
    return criteria_to_mapping(SearchCriteria("Profile/Search_Criteria.md", "0" * 64, (rule,)))["rules"][0]


def _hash_mapping(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
