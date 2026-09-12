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
    criteria = resolve_workspace_criteria(workspace, criteria)
    baseline = load_indexes(workspace)
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
    with workspace_lock(workspace):
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
    if type(reason_codes) is not tuple or not reason_codes or len(reason_codes) > 3 or any(
        type(code) is not str or _REASON_CODE.fullmatch(code) is None
        for code in reason_codes
    ):
        raise ValueError("rejection reason codes must use bounded machine-code syntax")
    return {
        "identity": dict(identity),
        "decision": "hard_filter_rejection" if hard_rejected else "semantic_non_match",
        "disposition": (
            item.assessment.disposition
            if item.assessment is not None
            else "not_assessed"
        ),
        "filter_result": filter_outcome.result,
        "reason_codes": list(reason_codes),
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
    rationale = f"{rejection['decision']}:{','.join(rejection['reason_codes'])}"
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
        "decision": rejection["decision"],
        "filter_result": rejection["filter_result"],
        "reason_codes": list(rejection["reason_codes"]),
        "rationale_summary": rationale,
        "criteria_hash": rejection["criteria_hash"],
        "readable_criteria_sha256": rejection["readable_criteria_sha256"],
        "assessment_hash": rejection["assessment_hash"],
    }
    if upstream is not None:
        payload["upstream_source_receipt_reference"] = upstream
    digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    relative = f"Runs/discovery/sources/receipt-{digest}.json"
    destination = workspace.root / relative
    with workspace_lock(workspace):
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
    path = workspace.root / reference
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to((workspace.runs / "discovery" / "sources").resolve())
    except (OSError, ValueError) as exc:
        raise ValueError("source receipt reference is missing or outside discovery evidence") from exc
    if path.is_symlink() or not path.is_file():
        raise ValueError("source receipt reference must identify a regular file")
    try:
        receipt = load_json(path)
    except (OSError, ValueError) as exc:
        raise ValueError("source receipt is invalid") from exc
    if hashlib.sha256(_canonical_json(receipt)).hexdigest() != match.group(1):
        raise ValueError("source receipt content hash does not match its reference")
    identity = receipt.get("identity")
    snapshot = receipt.get("source_snapshot")
    if not isinstance(identity, Mapping) or not isinstance(snapshot, Mapping) or (
        identity.get("source"), identity.get("source_record_id"), snapshot.get("raw_field_hash")
    ) != (
        item.candidate.source, item.candidate.source_record_id, item.candidate.raw_field_hash
    ):
        raise ValueError("source receipt does not match the reviewed candidate")
    return reference
