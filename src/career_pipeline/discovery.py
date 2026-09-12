"""Persist reviewed discovery results into canonical local job folders."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Mapping, Sequence

from .atomic import atomic_write_json
from .checkpoints import DiscoveryState, stable_review_batch
from .criteria import HardFilterOutcome, SearchCriteria, evaluate_hard_filters
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
    criteria_evidence: Mapping[str, object] = field(default_factory=dict)
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
    reviewed: Sequence[ReviewedJob],
) -> Path:
    digest = hashlib.sha256()
    digest.update(occurred_at.encode("utf-8"))
    for item in reviewed:
        digest.update(candidate_key(item.candidate).encode("utf-8"))
        digest.update(b"\n")
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
            rejections.append(
                _rejection_evidence(
                    item,
                    identity,
                    filter_outcome,
                    criteria=(
                        criteria.readable_criteria_sha256
                        if criteria is not None
                        else None
                    ),
                    hard_rejected=hard_rejected,
                )
            )
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
    evidence_path = _run_evidence_path(workspace, occurred_at, reviewed)
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


def _assessment_hash(
    assessment: JobAssessment | None,
    filter_outcome: HardFilterOutcome,
) -> str:
    payload = json.dumps(
        (
            asdict(assessment)
            if assessment is not None
            else {
                "filter_result": filter_outcome.result,
                "decisions": [asdict(decision) for decision in filter_outcome.decisions],
            }
        ),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _source_receipt_reference(item: ReviewedJob) -> str:
    if (
        isinstance(item.source_receipt_reference, str)
        and 0 < len(item.source_receipt_reference) <= 512
        and "\n" not in item.source_receipt_reference
        and "\r" not in item.source_receipt_reference
    ):
        return item.source_receipt_reference
    candidate = item.candidate
    return (
        f"source-record:{candidate.source}:{candidate.source_record_id}:"
        f"{candidate.raw_field_hash}"
    )


def _rejection_evidence(
    item: ReviewedJob,
    identity: Mapping[str, object],
    filter_outcome: HardFilterOutcome,
    *,
    criteria: str | None,
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
        "source_receipt_reference": _source_receipt_reference(item),
        "criteria_hash": criteria,
        "assessment_hash": _assessment_hash(item.assessment, filter_outcome),
    }
