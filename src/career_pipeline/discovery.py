"""Persist reviewed discovery results into canonical local job folders."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Mapping, Sequence

from .atomic import atomic_write_json, load_json
from .checkpoints import DiscoveryState, stable_review_batch
from .criteria import (
    HardFilterOutcome,
    SearchCriteria,
    evaluate_hard_filters,
    evidence_to_mapping,
    normalized_evidence_from_mapping,
    normalized_evidence_is_valid,
    resolve_workspace_criteria,
)
from .contracts import WorkspacePaths
from .dedupe import candidate_key
from .evaluation import JobAssessment
from .indexes import load_indexes, rebuild_indexes
from .job_store import (
    DuplicateJobError,
    create_job,
    reverify_job,
    workspace_lock,
)
from .sources.base import CandidateJob


@dataclass(frozen=True)
class ReviewedJob:
    candidate: CandidateJob
    assessment: JobAssessment | None
    posting_markdown: str
    assessment_markdown: str
    criteria_evidence: object = field(default_factory=tuple)
    source_receipt_reference: str | None = None


@dataclass(frozen=True)
class DiscoveryOutcome:
    state: DiscoveryState
    created_job_ids: tuple[str, ...]
    duplicate_keys: tuple[str, ...]
    non_match_keys: tuple[str, ...]
    meaningful_change_job_ids: tuple[str, ...]
    run_evidence: Path


def _run_evidence_path(
    workspace: WorkspacePaths,
    occurred_at: str,
    decision_identity: object,
) -> Path:
    digest = hashlib.sha256()
    digest.update(occurred_at.encode("utf-8"))
    digest.update(_canonical_json(decision_identity))
    return workspace.runs / "discovery" / f"run-{digest.hexdigest()[:16]}.json"


def deliver_reviewed_jobs(
    workspace: WorkspacePaths,
    state: DiscoveryState,
    reviewed: Sequence[ReviewedJob],
    *,
    occurred_at: str,
    criteria: SearchCriteria | None = None,
) -> DiscoveryOutcome:
    if not occurred_at:
        raise ValueError("occurred_at is required")
    with workspace_lock(workspace):
        return _deliver_reviewed_jobs_locked(
            workspace,
            state,
            reviewed,
            occurred_at=occurred_at,
            criteria=criteria,
        )


def _deliver_reviewed_jobs_locked(
    workspace: WorkspacePaths,
    state: DiscoveryState,
    reviewed: Sequence[ReviewedJob],
    *,
    occurred_at: str,
    criteria: SearchCriteria | None,
) -> DiscoveryOutcome:
    criteria = resolve_workspace_criteria(workspace, criteria)
    baseline = load_indexes(workspace)
    _revalidate_criteria_snapshot(workspace, criteria)
    raw_identities = baseline.deduplication.get("identities", {})
    identities = raw_identities if isinstance(raw_identities, dict) else {}
    created: list[str] = []
    duplicates: list[str] = []
    non_matches: list[str] = []
    meaningful_changes: list[str] = []
    filter_outcomes: list[dict[str, object]] = []
    rejections: list[dict[str, object]] = []
    canonical_jobs = dict(state.canonical_jobs)
    for item in reviewed:
        key = candidate_key(item.candidate)
        filter_outcome = (
            evaluate_hard_filters(
                item.candidate,
                criteria,
                evidence=item.criteria_evidence,
            )
            if criteria is not None
            else HardFilterOutcome("pass", ())
        )
        identity = _compact_identity(item.candidate, key)
        filter_outcomes.append(
            {
                "identity": identity,
                "result": filter_outcome.result,
                "decisions": [asdict(decision) for decision in filter_outcome.decisions],
                "criteria_hash": (
                    criteria.structured_sha256 if criteria is not None else None
                ),
                "readable_criteria_sha256": (
                    criteria.readable_criteria_sha256 if criteria is not None else None
                ),
            }
        )
        hard_rejected = filter_outcome.result == "confirmed_mismatch"
        if not hard_rejected and item.assessment is None:
            raise ValueError("semantic assessment is required after hard filters pass")
        if hard_rejected or (
            item.assessment is not None
            and item.assessment.disposition == "non_match"
        ):
            non_matches.append(key)
            _revalidate_criteria_snapshot(workspace, criteria)
            rejection = _rejection_evidence(
                    item,
                    identity,
                    filter_outcome,
                    criteria=criteria,
                    hard_rejected=hard_rejected,
                )
            rejection["evidence_receipt_reference"] = _persist_rejection_receipt(
                workspace,
                item,
                rejection,
                filter_outcome,
            )
            rejection["source_receipt_reference"] = rejection["evidence_receipt_reference"]
            rejections.append(rejection)
            continue
        if key in identities:
            duplicates.append(key)
            matched = identities[key]
            if isinstance(matched, list) and len(matched) == 1:
                _revalidate_criteria_snapshot(workspace, criteria)
                job_id = str(matched[0])
                canonical_jobs[key] = job_id
                result = reverify_job(
                    workspace,
                    job_id,
                    item.candidate,
                    item.assessment,
                    posting_markdown=item.posting_markdown,
                    assessment_markdown=item.assessment_markdown,
                    occurred_at=occurred_at,
                )
                if result.changed:
                    meaningful_changes.append(job_id)
            continue
        try:
            _revalidate_criteria_snapshot(workspace, criteria)
            record = create_job(
                workspace,
                item.candidate,
                item.assessment,
                posting_markdown=item.posting_markdown,
                assessment_markdown=item.assessment_markdown,
                occurred_at=occurred_at,
            )
        except DuplicateJobError as exc:
            duplicates.append(key)
            if len(exc.job_ids) == 1:
                _revalidate_criteria_snapshot(workspace, criteria)
                job_id = exc.job_ids[0]
                canonical_jobs[key] = job_id
                result = reverify_job(
                    workspace,
                    job_id,
                    item.candidate,
                    item.assessment,
                    posting_markdown=item.posting_markdown,
                    assessment_markdown=item.assessment_markdown,
                    occurred_at=occurred_at,
                )
                if result.changed:
                    meaningful_changes.append(job_id)
            continue
        job_id = str(record["job_id"])
        created.append(job_id)
        canonical_jobs[key] = job_id
    rebuild_indexes(workspace)
    updated_state = replace(
        state,
        stable_review_batch=stable_review_batch(tuple(created)),
        canonical_jobs=canonical_jobs,
    )
    evidence_path = _run_evidence_path(
        workspace,
        occurred_at,
        {"filter_outcomes": filter_outcomes, "rejections": rejections},
    )
    _revalidate_criteria_snapshot(workspace, criteria)
    atomic_write_json(
        evidence_path,
        {
            "schema_version": 2,
            "occurred_at": occurred_at,
            "created_job_ids": created,
            "duplicate_keys": duplicates,
            "non_match_keys": non_matches,
            "meaningful_change_job_ids": meaningful_changes,
            "filter_outcomes": filter_outcomes,
            "rejections": rejections,
        },
    )
    return DiscoveryOutcome(
        state=updated_state,
        created_job_ids=tuple(created),
        duplicate_keys=tuple(duplicates),
        non_match_keys=tuple(non_matches),
        meaningful_change_job_ids=tuple(dict.fromkeys(meaningful_changes)),
        run_evidence=evidence_path,
    )


def _revalidate_criteria_snapshot(
    workspace: WorkspacePaths,
    expected: SearchCriteria | None,
) -> None:
    current = resolve_workspace_criteria(workspace, expected)
    if (current is None) != (expected is None) or (
        current is not None
        and expected is not None
        and current.structured_sha256 != expected.structured_sha256
    ):
        raise ValueError("approved search criteria changed during discovery delivery")


def _compact_identity(candidate: CandidateJob, key: str) -> dict[str, object]:
    return {
        "candidate_key": key,
        "source": candidate.source,
        "source_record_id": candidate.source_record_id,
        "requisition_id": candidate.requisition_id,
        "employer": candidate.employer,
        "title": candidate.title,
    }


_REASON_CODE = re.compile(r"[a-z][a-z0-9_]{2,63}")
_RECEIPT_REFERENCE = re.compile(
    r"Runs/discovery/sources/receipt-([0-9a-f]{64})\.json"
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _assessment_hash(
    assessment: JobAssessment | None,
    filter_outcome: HardFilterOutcome,
    criteria: SearchCriteria | None,
) -> str:
    payload = {
        "assessment": asdict(assessment) if assessment is not None else None,
        "filter_result": filter_outcome.result,
        "filter_decisions": [asdict(decision) for decision in filter_outcome.decisions],
        "criteria_hash": criteria.structured_sha256 if criteria is not None else None,
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _rejection_evidence(
    item: ReviewedJob,
    identity: Mapping[str, object],
    filter_outcome: HardFilterOutcome,
    *,
    criteria: SearchCriteria | None,
    hard_rejected: bool,
) -> dict[str, object]:
    reason_codes = (
        filter_outcome.reason_codes
        if hard_rejected
        else (
            item.assessment.reason_codes or ("semantic_non_match",)
            if item.assessment is not None
            else ()
        )
    )
    if type(reason_codes) is not tuple or not reason_codes or any(
        type(code) is not str or _REASON_CODE.fullmatch(code) is None
        for code in reason_codes
    ):
        raise ValueError("rejection reason codes must use bounded machine-code syntax")
    unique_reason_codes = tuple(dict.fromkeys(reason_codes))
    return {
        "identity": dict(identity),
        "decision": "hard_filter_rejection" if hard_rejected else "semantic_non_match",
        "disposition": (
            item.assessment.disposition
            if item.assessment is not None
            else "not_assessed"
        ),
        "filter_result": filter_outcome.result,
        "reason_codes": list(unique_reason_codes[:3]),
        "reason_code_count": len(unique_reason_codes),
        "criteria_hash": criteria.structured_sha256 if criteria is not None else None,
        "readable_criteria_sha256": (
            criteria.readable_criteria_sha256 if criteria is not None else None
        ),
        "assessment_hash": _assessment_hash(item.assessment, filter_outcome, criteria),
    }


def _persist_rejection_receipt(
    workspace: WorkspacePaths,
    item: ReviewedJob,
    rejection: Mapping[str, object],
    filter_outcome: HardFilterOutcome,
) -> str:
    upstream = _validated_existing_receipt(workspace, item)
    candidate = item.candidate
    rationale = f"{rejection['decision']}:bounded_reason_summary"
    payload: dict[str, object] = {
        "schema_version": 1,
        "identity": {
            **dict(rejection["identity"]),
            "posting_url": candidate.posting_url,
            "application_url": candidate.application_url,
        },
        "source_snapshot": {
            "verified_at": candidate.verified_at,
            "verification_status": candidate.verification_status,
            "raw_field_hash": candidate.raw_field_hash,
        },
        "responsibility_evidence": [
            " ".join(value.split())[:160]
            for value in candidate.responsibilities[:3]
            if value.strip()
        ],
        "normalized_evidence": [
            evidence_to_mapping(value) for value in filter_outcome.normalized_evidence
        ],
        "filter_decisions": [asdict(value) for value in filter_outcome.decisions],
        "decision": rejection["decision"],
        "filter_result": rejection["filter_result"],
        "reason_codes": list(rejection["reason_codes"]),
        "reason_code_count": rejection["reason_code_count"],
        "rationale_summary": rationale,
        "criteria_hash": rejection["criteria_hash"],
        "readable_criteria_sha256": rejection["readable_criteria_sha256"],
        "assessment_hash": rejection["assessment_hash"],
    }
    if upstream is not None:
        payload["upstream_source_receipt_reference"] = upstream
    _validate_receipt_payload(payload, candidate)
    digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    relative = f"Runs/discovery/sources/receipt-{digest}.json"
    directory = _safe_receipt_directory(workspace, create=True)
    destination = directory / f"receipt-{digest}.json"
    if destination.is_symlink() or destination.resolve().parent != directory.resolve():
        raise ValueError("generated rejection receipt path is unsafe")
    if destination.exists():
        if load_json(destination) != payload:
            raise ValueError("immutable rejection receipt conflicts with existing data")
    else:
        atomic_write_json(destination, payload)
    return relative


def _validated_existing_receipt(
    workspace: WorkspacePaths,
    item: ReviewedJob,
) -> str | None:
    reference = item.source_receipt_reference
    if reference is None:
        return None
    if type(reference) is not str:
        raise ValueError("source receipt reference is invalid")
    match = _RECEIPT_REFERENCE.fullmatch(reference)
    if match is None:
        raise ValueError("source receipt reference is invalid")
    directory = _safe_receipt_directory(workspace, create=False)
    path = workspace.root / reference
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(workspace.root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ValueError("source receipt reference is missing or outside discovery evidence") from exc
    if (
        path.is_symlink()
        or not path.is_file()
        or resolved.parent != directory.resolve(strict=True)
    ):
        raise ValueError("source receipt reference must identify a regular file")
    try:
        receipt = load_json(path)
    except (OSError, ValueError) as exc:
        raise ValueError("source receipt is invalid") from exc
    if hashlib.sha256(_canonical_json(receipt)).hexdigest() != match.group(1):
        raise ValueError("source receipt content hash does not match its reference")
    _validate_receipt_payload(receipt, item.candidate)
    return reference


def _safe_receipt_directory(workspace: WorkspacePaths, *, create: bool) -> Path:
    try:
        root = workspace.root.resolve(strict=True)
    except OSError as exc:
        raise ValueError("workspace root is unavailable") from exc
    directory = workspace.runs / "discovery" / "sources"
    ancestors = (workspace.runs, workspace.runs / "discovery")
    for path in ancestors:
        if path.is_symlink() or not path.is_dir():
            raise ValueError("discovery receipt directory has an unsafe ancestor")
        try:
            path.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as exc:
            raise ValueError("discovery receipt directory escapes the workspace") from exc
    if directory.is_symlink():
        raise ValueError("discovery receipt directory must not be a symlink")
    if create:
        directory.mkdir(exist_ok=True)
    if not directory.is_dir():
        raise ValueError("discovery receipt directory is unavailable")
    try:
        directory.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError("discovery receipt directory escapes the workspace") from exc
    return directory


def _validate_receipt_payload(
    payload: object,
    candidate: CandidateJob,
) -> None:
    required = {
        "schema_version", "identity", "source_snapshot", "responsibility_evidence",
        "normalized_evidence", "filter_decisions", "decision", "filter_result",
        "reason_codes", "reason_code_count", "rationale_summary", "criteria_hash",
        "readable_criteria_sha256", "assessment_hash",
    }
    if type(payload) is not dict or set(payload) not in (
        required,
        required | {"upstream_source_receipt_reference"},
    ):
        raise ValueError("rejection receipt fields are invalid")
    identity = payload["identity"]
    expected_identity = {
        "candidate_key": candidate_key(candidate),
        "source": candidate.source,
        "source_record_id": candidate.source_record_id,
        "requisition_id": candidate.requisition_id,
        "employer": candidate.employer,
        "title": candidate.title,
        "posting_url": candidate.posting_url,
        "application_url": candidate.application_url,
    }
    snapshot = payload["source_snapshot"]
    expected_snapshot = {
        "verified_at": candidate.verified_at,
        "verification_status": candidate.verification_status,
        "raw_field_hash": candidate.raw_field_hash,
    }
    reasons = payload["reason_codes"]
    reason_count = payload["reason_code_count"]
    decision = payload["decision"]
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
        or identity != expected_identity
        or snapshot != expected_snapshot
        or type(reasons) is not list
        or not 1 <= len(reasons) <= 3
        or len(reasons) != len(set(reasons))
        or any(type(code) is not str or _REASON_CODE.fullmatch(code) is None for code in reasons)
        or type(reason_count) is not int
        or reason_count < len(reasons)
        or len(reasons) != min(reason_count, 3)
        or type(decision) is not str
        or decision not in {"hard_filter_rejection", "semantic_non_match"}
        or type(payload["filter_result"]) is not str
        or payload["filter_result"] not in {"pass", "unknown", "confirmed_mismatch"}
        or (decision == "hard_filter_rejection" and payload["filter_result"] != "confirmed_mismatch")
        or (decision == "semantic_non_match" and payload["filter_result"] == "confirmed_mismatch")
        or payload["rationale_summary"] != f"{decision}:bounded_reason_summary"
        or not _nullable_hash(payload["criteria_hash"])
        or not _nullable_hash(payload["readable_criteria_sha256"])
        or ((payload["criteria_hash"] is None) != (payload["readable_criteria_sha256"] is None))
        or type(payload["assessment_hash"]) is not str
        or re.fullmatch(r"[0-9a-f]{64}", payload["assessment_hash"]) is None
    ):
        raise ValueError("rejection receipt contract is invalid")
    if (
        type(identity) is not dict
        or set(identity) != set(expected_identity)
        or any(
            type(identity[name]) is not str or not identity[name]
            for name in (
                "candidate_key", "source", "source_record_id", "employer", "title",
                "posting_url", "application_url",
            )
        )
        or (
            identity["requisition_id"] is not None
            and (type(identity["requisition_id"]) is not str or not identity["requisition_id"])
        )
        or type(snapshot) is not dict
        or set(snapshot) != set(expected_snapshot)
        or any(type(snapshot[name]) is not str or not snapshot[name] for name in snapshot)
        or re.fullmatch(r"[0-9a-f]{64}", snapshot["raw_field_hash"]) is None
    ):
        raise ValueError("rejection receipt source identity is invalid")
    responsibilities = payload["responsibility_evidence"]
    if type(responsibilities) is not list or len(responsibilities) > 3 or any(
        type(value) is not str or not value.strip() or len(value) > 160
        for value in responsibilities
    ):
        raise ValueError("rejection receipt responsibility evidence is invalid")
    normalized = payload["normalized_evidence"]
    if type(normalized) is not list:
        raise ValueError("rejection receipt normalized evidence is invalid")
    for raw in normalized:
        value = normalized_evidence_from_mapping(raw)
        if (
            value is None
            or not normalized_evidence_is_valid(value)
            or evidence_to_mapping(value) != raw
            or (value.source, value.source_record_id, value.source_field_hash)
            != (candidate.source, candidate.source_record_id, candidate.raw_field_hash)
        ):
            raise ValueError("rejection receipt normalized evidence is invalid")
    decisions = payload["filter_decisions"]
    if type(decisions) is not list or any(not _valid_filter_decision(value) for value in decisions):
        raise ValueError("rejection receipt filter decisions are invalid")
    if decision == "hard_filter_rejection":
        complete_codes = tuple(dict.fromkeys(
            value["reason_code"]
            for value in decisions
            if value["result"] == "confirmed_mismatch"
        ))
        if reason_count != len(complete_codes) or reasons != list(complete_codes[:3]):
            raise ValueError("rejection receipt reason summary is invalid")
    upstream = payload.get("upstream_source_receipt_reference")
    if upstream is not None and (
        type(upstream) is not str or _RECEIPT_REFERENCE.fullmatch(upstream) is None
    ):
        raise ValueError("rejection receipt upstream reference is invalid")


def _nullable_hash(value: object) -> bool:
    return value is None or (
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    )


def _valid_filter_decision(value: object) -> bool:
    return (
        type(value) is dict
        and set(value) == {
            "criterion_id", "dimension", "subject", "result", "reason_code",
            "rule_hash", "evidence_hash",
        }
        and type(value["criterion_id"]) is str
        and re.fullmatch(r"[a-z][a-z0-9-]{2,63}", value["criterion_id"]) is not None
        and type(value["dimension"]) is str
        and bool(value["dimension"])
        and type(value["subject"]) is str
        and bool(value["subject"])
        and type(value["result"]) is str
        and value["result"] in {"pass", "unknown", "confirmed_mismatch"}
        and type(value["reason_code"]) is str
        and _REASON_CODE.fullmatch(value["reason_code"]) is not None
        and type(value["rule_hash"]) is str
        and re.fullmatch(r"[0-9a-f]{64}", value["rule_hash"]) is not None
        and type(value["evidence_hash"]) is str
        and re.fullmatch(r"[0-9a-f]{64}", value["evidence_hash"]) is not None
    )
