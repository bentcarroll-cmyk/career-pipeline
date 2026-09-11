"""Conservative lifecycle evidence matching and minimal receipts."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Sequence


@dataclass(frozen=True)
class LifecycleCandidate:
    ticket_id: str
    employer: str
    title: str
    requisition_id: str | None


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
    ticket_id: str | None = None
    target_status: str | None = None
    reason: str = ""


_EVENT_STATUS = {
    "application_confirmation": "Applied",
    "rejection": "Closed",
    "interview_invitation": "Interviewing",
    "offer": "Offer",
}
_SPACE = re.compile(r"\s+")


def _normalize(value: str | None) -> str:
    return _SPACE.sub(
        " ",
        unicodedata.normalize("NFKC", value or "").casefold().strip(),
    )


def _matches(
    evidence: LifecycleEvidence,
    candidate: LifecycleCandidate,
) -> bool:
    if _normalize(evidence.employer) != _normalize(candidate.employer):
        return False
    if evidence.requisition_id and candidate.requisition_id:
        return _normalize(evidence.requisition_id) == _normalize(
            candidate.requisition_id
        )
    return bool(
        evidence.role_title
        and _normalize(evidence.role_title) == _normalize(candidate.title)
    )


def classify_lifecycle_evidence(
    evidence: LifecycleEvidence,
    candidates: Sequence[LifecycleCandidate],
    previously_seen: Sequence[str] = (),
) -> LifecycleDecision:
    if evidence.opaque_id in set(previously_seen):
        return LifecycleDecision("ignore", reason="evidence_already_seen")
    if evidence.source_kind not in {"gmail", "calendar"}:
        return LifecycleDecision("ignore", reason="source_not_enabled_for_lifecycle")
    if evidence.event_class not in _EVENT_STATUS:
        return LifecycleDecision("ignore", reason="event_class_not_actionable")
    if evidence.contradictory:
        return LifecycleDecision("needs_review", reason="contradictory_evidence")
    matches = tuple(candidate for candidate in candidates if _matches(evidence, candidate))
    if len(matches) != 1:
        return LifecycleDecision(
            "needs_review",
            reason="exact_role_match_required",
        )
    match = matches[0]
    return LifecycleDecision(
        "apply_update",
        ticket_id=match.ticket_id,
        target_status=_EVENT_STATUS[evidence.event_class],
        reason="exact_unambiguous_evidence",
    )


def minimal_receipt(
    evidence: LifecycleEvidence,
    decision: LifecycleDecision,
) -> dict[str, object]:
    opaque_hash = hashlib.sha256(evidence.opaque_id.encode("utf-8")).hexdigest()
    return {
        "source_kind": evidence.source_kind,
        "source_receipt_hash": opaque_hash,
        "observed_at": evidence.observed_at,
        "event_class": evidence.event_class,
        "action": decision.action,
        "ticket_id": decision.ticket_id,
        "target_status": decision.target_status,
        "reason": decision.reason,
    }
