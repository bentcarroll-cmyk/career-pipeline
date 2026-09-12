"""Conservative lifecycle evidence matching into canonical local job status."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .atomic import atomic_write_json, load_json
from .contracts import WorkspacePaths
from .indexes import load_indexes
from .job_store import (
    _record_lifecycle_status_observation_locked,
    _update_job_status_locked,
    read_job,
    workspace_lock,
)
from .timestamps import TimestampError, parse_instant


class LifecycleReconciliationError(ValueError):
    pass


@dataclass(frozen=True)
class LifecycleCandidate:
    job_id: str
    employer: str
    title: str
    requisition_id: str | None
    status: str = "new"
    status_observed_at: str | None = None
    status_freshness_known: bool = True


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
_RECEIPT_HASH = re.compile(r"[a-f0-9]{64}")
_RECEIPT_FIELDS = {
    "source_kind",
    "source_receipt_hash",
    "observed_at",
    "event_class",
    "action",
    "job_id",
    "target_status",
    "reason",
}
_APPLY_REASON = "exact_unambiguous_evidence"
_UNMATCHED_REVIEW_REASONS = {
    "contradictory_evidence",
    "exact_role_match_required",
}
_MATCHED_REVIEW_REASONS = {
    "status_transition_requires_review",
    "canonical_status_freshness_unavailable",
    "lifecycle_evidence_freshness_unavailable",
    "canonical_status_newer_than_evidence",
}
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
    if match.status != target_status:
        if not match.status_freshness_known:
            return LifecycleDecision(
                "needs_review",
                job_id=match.job_id,
                target_status=target_status,
                reason="canonical_status_freshness_unavailable",
            )
        if match.status_observed_at is not None:
            try:
                status_instant = parse_instant(match.status_observed_at)
                evidence_instant = parse_instant(evidence.observed_at)
            except TimestampError:
                return LifecycleDecision(
                    "needs_review",
                    job_id=match.job_id,
                    target_status=target_status,
                    reason="lifecycle_evidence_freshness_unavailable",
                )
            if status_instant > evidence_instant:
                return LifecycleDecision(
                    "needs_review",
                    job_id=match.job_id,
                    target_status=target_status,
                    reason="canonical_status_newer_than_evidence",
                )
    return LifecycleDecision(
        "apply_update",
        job_id=match.job_id,
        target_status=target_status,
        reason=_APPLY_REASON,
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
        status_observed_at, freshness_known = _latest_status_observation(
            job_dir / "events.jsonl",
            job_dir.name,
            str(record["status"]),
        )
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
                status_observed_at=status_observed_at,
                status_freshness_known=freshness_known,
            )
        )
    return tuple(candidates)


def _latest_status_observation(
    events_path: Path,
    job_id: str,
    status: str,
) -> tuple[str | None, bool]:
    latest_value: str | None = None
    latest_instant = None
    try:
        lines = events_path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            event = json.loads(line)
            if not isinstance(event, Mapping):
                return None, False
            if event.get("job_id") != job_id:
                return None, False
            occurred_at = event.get("occurred_at")
            event_status = event.get("status")
            event_type = event.get("event_type")
            prior_status = event.get("prior_status")
            if not isinstance(occurred_at, str) or not isinstance(
                event_status, str
            ):
                return None, False
            if not isinstance(event_type, str) or "prior_status" not in event:
                return None, False
            if prior_status is not None and not isinstance(prior_status, str):
                return None, False
            occurred_instant = parse_instant(occurred_at)
            is_status_decision = (
                prior_status != event_status
                or event_type == "lifecycle_status_observed"
            )
            if event_status == status and is_status_decision and (
                latest_instant is None or occurred_instant > latest_instant
            ):
                latest_value = occurred_at
                latest_instant = occurred_instant
    except (OSError, UnicodeError, ValueError, TimestampError):
        return None, False
    return latest_value, latest_value is not None


def _seen_receipts(workspace: WorkspacePaths) -> dict[str, Path]:
    seen: dict[str, Path] = {}
    for path in sorted((workspace.runs / "lifecycle").glob("receipt-*.json")):
        try:
            receipt = load_json(path)
        except (OSError, UnicodeError, ValueError):
            raise LifecycleReconciliationError(
                "lifecycle receipt is invalid: unreadable"
            ) from None
        _validate_receipt(path, receipt)
        receipt_hash = str(receipt["source_receipt_hash"])
        if receipt_hash in seen and seen[receipt_hash] != path:
            raise LifecycleReconciliationError(
                "lifecycle receipts are invalid: duplicate_source_hash"
            )
        seen[receipt_hash] = path
    return seen


def _validate_receipt(path: Path, receipt: Mapping[str, object]) -> None:
    receipt_hash = receipt.get("source_receipt_hash")
    source_kind = receipt.get("source_kind")
    observed_at = receipt.get("observed_at")
    event_class = receipt.get("event_class")
    action = receipt.get("action")
    job_id = receipt.get("job_id")
    target_status = receipt.get("target_status")
    reason = receipt.get("reason")
    expected_name = (
        f"receipt-{receipt_hash[:20]}.json"
        if isinstance(receipt_hash, str)
        else None
    )
    is_legacy_nonactionable_ignore = (
        isinstance(event_class, str)
        and bool(event_class.strip())
        and event_class not in _EVENT_STATUS
        and action == "ignore"
        and job_id is None
        and target_status is None
        and reason == "event_class_not_actionable"
    )
    structurally_invalid = (
        set(receipt) != _RECEIPT_FIELDS
        or not isinstance(source_kind, str)
        or source_kind not in _LIFECYCLE_SOURCES
        or not isinstance(receipt_hash, str)
        or _RECEIPT_HASH.fullmatch(receipt_hash) is None
        or path.name != expected_name
        or not isinstance(observed_at, str)
        or not observed_at.strip()
        or not isinstance(event_class, str)
        or (
            event_class not in _EVENT_STATUS
            and not is_legacy_nonactionable_ignore
        )
        or not isinstance(action, str)
        or action not in {"apply_update", "needs_review", "ignore"}
        or (job_id is not None and (
            not isinstance(job_id, str) or _JOB_ID.fullmatch(job_id) is None
        ))
        or (
            target_status is not None
            and (
                not isinstance(target_status, str)
                or target_status not in set(_EVENT_STATUS.values())
            )
        )
        or not isinstance(reason, str)
        or not reason.strip()
    )
    if structurally_invalid:
        raise LifecycleReconciliationError(
            "lifecycle receipt is invalid: receipt_contract"
        )
    try:
        parse_instant(str(observed_at))
    except TimestampError:
        raise LifecycleReconciliationError(
            "lifecycle receipt is invalid: observed_at"
        ) from None
    assert isinstance(event_class, str)
    expected_target = _EVENT_STATUS.get(event_class)
    if is_legacy_nonactionable_ignore:
        coherent = True
    elif action == "apply_update":
        coherent = (
            job_id is not None
            and target_status == expected_target
            and reason == _APPLY_REASON
        )
    elif action == "needs_review" and reason in _UNMATCHED_REVIEW_REASONS:
        coherent = job_id is None and target_status is None
    elif action == "needs_review" and reason in _MATCHED_REVIEW_REASONS:
        coherent = job_id is not None and target_status == expected_target
    else:
        coherent = False
    if not coherent:
        raise LifecycleReconciliationError(
            "lifecycle receipt is invalid: decision_contract"
        )


def _committed_lifecycle_result(
    workspace: WorkspacePaths,
    evidence: LifecycleEvidence,
    receipt_hash: str,
) -> tuple[LifecycleDecision, dict[str, object]] | None:
    matches: list[tuple[LifecycleDecision, dict[str, object]]] = []
    for job_dir in sorted(workspace.jobs.iterdir(), key=lambda path: path.name):
        if not job_dir.is_dir() or _JOB_ID.fullmatch(job_dir.name) is None:
            continue
        try:
            lines = (job_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(event, Mapping):
                continue
            metadata = event.get("metadata")
            if not isinstance(metadata, Mapping):
                continue
            if metadata.get("source_receipt_hash") != receipt_hash:
                continue
            event_class = metadata.get("event_class")
            target_status = event.get("status")
            prior_status = event.get("prior_status")
            event_type = event.get("event_type")
            occurred_at = event.get("occurred_at")
            source_kind = metadata.get("source_kind", evidence.source_kind)
            decision_reason = metadata.get(
                "lifecycle_decision_reason",
                _APPLY_REASON,
            )
            decision_action = metadata.get(
                "lifecycle_decision_action",
                "apply_update",
            )
            recorded_target = metadata.get(
                "lifecycle_target_status",
                target_status,
            )
            if (
                not isinstance(event_type, str)
                or event_type not in {"status_changed", "lifecycle_status_observed"}
                or event.get("job_id") != job_dir.name
                or not isinstance(event_class, str)
                or event_class not in _EVENT_STATUS
                or target_status != _EVENT_STATUS[event_class]
                or recorded_target != target_status
                or decision_action != "apply_update"
                or not isinstance(occurred_at, str)
                or not occurred_at.strip()
                or source_kind != evidence.source_kind
                or not isinstance(decision_reason, str)
                or decision_reason != _APPLY_REASON
                or (
                    event_type == "status_changed"
                    and prior_status == target_status
                )
                or (
                    event_type == "lifecycle_status_observed"
                    and prior_status != target_status
                )
            ):
                raise LifecycleReconciliationError(
                    "committed lifecycle evidence is invalid: event_conflict"
                )
            try:
                parse_instant(occurred_at)
            except TimestampError:
                raise LifecycleReconciliationError(
                    "committed lifecycle evidence is invalid: observed_at"
                ) from None
            decision = LifecycleDecision(
                "apply_update",
                job_id=job_dir.name,
                target_status=str(target_status),
                reason=decision_reason,
            )
            receipt = minimal_receipt(evidence, decision)
            receipt["observed_at"] = occurred_at
            receipt["event_class"] = event_class
            matches.append((decision, receipt))
    if not matches:
        return None
    first = matches[0]
    if any(item != first for item in matches[1:]):
        raise LifecycleReconciliationError(
            "committed lifecycle evidence is invalid: duplicate_conflict"
        )
    return first


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
    result: ReconciliationResult | None = None
    with workspace_lock(workspace):
        seen = _seen_receipts(workspace)
        if receipt_hash in seen:
            decision = LifecycleDecision(
                "ignore",
                reason="evidence_already_seen",
            )
            return ReconciliationResult(decision, seen[receipt_hash])
        if receipt_path.exists():
            raise LifecycleReconciliationError(
                "lifecycle receipt is invalid: source_hash_conflict"
            )
        committed_result = _committed_lifecycle_result(
            workspace,
            evidence,
            receipt_hash,
        )
        if committed_result is not None:
            decision, receipt = committed_result
            _validate_receipt(receipt_path, receipt)
            atomic_write_json(receipt_path, receipt)
            result = ReconciliationResult(decision, receipt_path)
            rebuild_indexes = True
        else:
            decision = classify_lifecycle_evidence(
                evidence,
                _candidates(workspace),
                (),
                enabled_sources=enabled_sources,
            )
            if decision.action == "ignore":
                return ReconciliationResult(decision, None)
            receipt = minimal_receipt(evidence, decision)
            _validate_receipt(receipt_path, receipt)
            if decision.action == "apply_update":
                assert decision.job_id is not None
                assert decision.target_status is not None
                metadata = {
                    "source_receipt_hash": receipt_hash,
                    "source_kind": evidence.source_kind,
                    "event_class": evidence.event_class,
                    "lifecycle_decision_action": decision.action,
                    "lifecycle_decision_reason": decision.reason,
                    "lifecycle_target_status": decision.target_status,
                }
                current = read_job(workspace, decision.job_id)
                if current["status"] == decision.target_status:
                    committed = _record_lifecycle_status_observation_locked(
                        workspace,
                        decision.job_id,
                        occurred_at=evidence.observed_at,
                        metadata=metadata,
                    )
                else:
                    committed = _update_job_status_locked(
                        workspace,
                        decision.job_id,
                        decision.target_status,
                        occurred_at=evidence.observed_at,
                        metadata=metadata,
                        allowed_prior_statuses=frozenset(
                            _ALLOWED_TRANSITIONS[decision.target_status]
                        ),
                    )
                    rebuild_indexes = True
                if committed["status"] != decision.target_status:
                    decision = LifecycleDecision(
                        "needs_review",
                        job_id=decision.job_id,
                        target_status=decision.target_status,
                        reason="status_transition_requires_review",
                    )
                    receipt = minimal_receipt(evidence, decision)
                    _validate_receipt(receipt_path, receipt)
            atomic_write_json(receipt_path, receipt)
            result = ReconciliationResult(decision, receipt_path)
    if rebuild_indexes:
        load_indexes(workspace)
    assert result is not None
    return result
