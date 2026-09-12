"""Conservative lifecycle evidence matching into canonical local job status."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .atomic import atomic_write_json, load_json
from .contracts import WorkspacePaths
from .indexes import load_indexes
from .job_store import _update_job_status_locked, read_job, workspace_lock


@dataclass(frozen=True)
class LifecycleCandidate:
    job_id: str
    employer: str
    title: str
    requisition_id: str | None
    status: str = "new"


@dataclass(frozen=True)
class LifecycleEvidence:
    source_kind: str
    opaque_id: str
    observed_at: str
    employer: str | None
    role_title: str | None
    requisition_id: str | None
    event_class: str
    contradictory: bool = False


@dataclass(frozen=True)
class LifecycleDecision:
    action: str
    job_id: str | None = None
    target_status: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class ReconciliationResult:
    decision: LifecycleDecision
    receipt_path: Path | None


_EVENT_STATUS = {
    "application_confirmation": "applied",
    "rejection": "closed",
    "interview_invitation": "interviewing",
    "offer": "offer",
}
_LIFECYCLE_SOURCES = {"gmail", "google-calendar"}
_JOB_ID = re.compile(r"JOB-[0-9]{6}")
_SPACE = re.compile(r"\s+")
_ALLOWED_TRANSITIONS = {
    "applied": {
        "new",
        "needs_confirmation",
        "prepare_application",
        "packet_ready",
    },
    "interviewing": {"prepare_application", "packet_ready", "applied"},
    "offer": {"interviewing"},
    "closed": {
        "new",
        "needs_confirmation",
        "prepare_application",
        "packet_ready",
        "applied",
        "interviewing",
    },
}


def _normalize(value: str | None) -> str:
    return _SPACE.sub(
        " ",
        unicodedata.normalize("NFKC", value or "").casefold().strip(),
    )


def evidence_receipt_hash(evidence: LifecycleEvidence) -> str:
    return hashlib.sha256(
        f"{evidence.source_kind}\x00{evidence.opaque_id}".encode("utf-8")
    ).hexdigest()


def _matches(
    evidence: LifecycleEvidence,
    candidate: LifecycleCandidate,
) -> bool:
    if _normalize(evidence.employer) != _normalize(candidate.employer):
        return False
    if evidence.requisition_id:
        return bool(
            candidate.requisition_id
            and _normalize(evidence.requisition_id)
            == _normalize(candidate.requisition_id)
        )
    return bool(
        evidence.role_title
        and _normalize(evidence.role_title) == _normalize(candidate.title)
    )


def classify_lifecycle_evidence(
    evidence: LifecycleEvidence,
    candidates: Sequence[LifecycleCandidate],
    previously_seen: Sequence[str] = (),
    *,
    enabled_sources: Sequence[str],
) -> LifecycleDecision:
    receipt_hash = evidence_receipt_hash(evidence)
    if receipt_hash in set(previously_seen):
        return LifecycleDecision("ignore", reason="evidence_already_seen")
    if (
        evidence.source_kind not in _LIFECYCLE_SOURCES
        or evidence.source_kind not in set(enabled_sources)
    ):
        return LifecycleDecision("ignore", reason="source_not_enabled_for_lifecycle")
    if evidence.event_class not in _EVENT_STATUS:
        return LifecycleDecision("ignore", reason="event_class_not_actionable")
    if evidence.contradictory:
        return LifecycleDecision("needs_review", reason="contradictory_evidence")
    matches = tuple(candidate for candidate in candidates if _matches(evidence, candidate))
    if len(matches) != 1:
        return LifecycleDecision("needs_review", reason="exact_role_match_required")
    match = matches[0]
    target_status = _EVENT_STATUS[evidence.event_class]
    if (
        match.status != target_status
        and match.status not in _ALLOWED_TRANSITIONS[target_status]
    ):
        return LifecycleDecision(
            "needs_review",
            job_id=match.job_id,
            target_status=target_status,
            reason="status_transition_requires_review",
        )
    return LifecycleDecision(
        "apply_update",
        job_id=match.job_id,
        target_status=target_status,
        reason="exact_unambiguous_evidence",
    )


def minimal_receipt(
    evidence: LifecycleEvidence,
    decision: LifecycleDecision,
) -> dict[str, object]:
    return {
        "source_kind": evidence.source_kind,
        "source_receipt_hash": evidence_receipt_hash(evidence),
        "observed_at": evidence.observed_at,
        "event_class": evidence.event_class,
        "action": decision.action,
        "job_id": decision.job_id,
        "target_status": decision.target_status,
        "reason": decision.reason,
    }


def _candidates(workspace: WorkspacePaths) -> tuple[LifecycleCandidate, ...]:
    candidates: list[LifecycleCandidate] = []
    for job_dir in sorted(workspace.jobs.iterdir(), key=lambda path: path.name):
        if not job_dir.is_dir() or _JOB_ID.fullmatch(job_dir.name) is None:
            continue
        record = read_job(workspace, job_dir.name)
        candidates.append(
            LifecycleCandidate(
                job_id=job_dir.name,
                employer=str(record["employer"]),
                title=str(record["title"]),
                requisition_id=(
                    str(record["requisition_id"])
                    if record.get("requisition_id")
                    else None
                ),
                status=str(record["status"]),
            )
        )
    return tuple(candidates)


def _seen_receipts(workspace: WorkspacePaths) -> dict[str, Path]:
    seen: dict[str, Path] = {}
    for path in sorted((workspace.runs / "lifecycle").glob("receipt-*.json")):
        try:
            receipt = load_json(path)
        except (OSError, ValueError):
            continue
        receipt_hash = receipt.get("source_receipt_hash")
        if isinstance(receipt_hash, str):
            seen[receipt_hash] = path
    return seen


def reconcile_lifecycle_evidence(
    workspace: WorkspacePaths,
    evidence: LifecycleEvidence,
    *,
    enabled_sources: Sequence[str],
) -> ReconciliationResult:
    receipt_hash = evidence_receipt_hash(evidence)
    receipt_path = (
        workspace.runs / "lifecycle" / f"receipt-{receipt_hash[:20]}.json"
    )
    rebuild_indexes = False
    with workspace_lock(workspace):
        seen = _seen_receipts(workspace)
        decision = classify_lifecycle_evidence(
            evidence,
            _candidates(workspace),
            tuple(seen),
            enabled_sources=enabled_sources,
        )
        if decision.reason == "evidence_already_seen":
            return ReconciliationResult(decision, seen[receipt_hash])
        if decision.reason == "source_not_enabled_for_lifecycle":
            return ReconciliationResult(decision, None)
        if decision.action == "apply_update":
            assert decision.job_id is not None
            assert decision.target_status is not None
            committed = _update_job_status_locked(
                workspace,
                decision.job_id,
                decision.target_status,
                occurred_at=evidence.observed_at,
                metadata={
                    "source_receipt_hash": receipt_hash,
                    "event_class": evidence.event_class,
                },
                allowed_prior_statuses=frozenset(
                    _ALLOWED_TRANSITIONS[decision.target_status]
                ),
            )
            if committed["status"] != decision.target_status:
                decision = LifecycleDecision(
                    "needs_review",
                    job_id=decision.job_id,
                    target_status=decision.target_status,
                    reason="status_transition_requires_review",
                )
            else:
                rebuild_indexes = True
        if not receipt_path.exists():
            atomic_write_json(receipt_path, minimal_receipt(evidence, decision))
    if rebuild_indexes:
        load_indexes(workspace)
    return ReconciliationResult(decision, receipt_path)
