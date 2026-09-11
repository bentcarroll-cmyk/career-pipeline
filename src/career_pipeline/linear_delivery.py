"""Build qualifying Linear issues and verify readback before delivery."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Mapping

from .checkpoints import DiscoveryState
from .dedupe import candidate_key
from .evaluation import JobAssessment
from .sources.base import CandidateJob


class DeliveryVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class LinearIssuePayload:
    candidate_key: str
    title: str
    team_id: str
    project_id: str
    labels: tuple[str, ...]
    description: str
    posting_url: str
    application_url: str

    @property
    def body_hash(self) -> str:
        return hashlib.sha256(self.description.encode("utf-8")).hexdigest()

    def to_readback(self, issue_id: str) -> dict[str, object]:
        return {
            "issue_id": issue_id,
            "title": self.title,
            "team_id": self.team_id,
            "project_id": self.project_id,
            "labels": list(self.labels),
            "description": self.description,
            "posting_url": self.posting_url,
            "application_url": self.application_url,
        }


@dataclass(frozen=True)
class DeliveryReceipt:
    candidate_key: str
    issue_id: str
    verified: bool
    body_hash: str


def _display(value: str | None) -> str:
    return value if value else "Not stated; needs confirmation"


def build_issue_payload(
    job: CandidateJob,
    assessment: JobAssessment,
    config: Mapping[str, object],
) -> LinearIssuePayload:
    if assessment.disposition not in {"strong_match", "worth_considering"}:
        raise ValueError("Linear issues are only for qualifying roles")
    team_id = config.get("team_id")
    project_id = config.get("project_id")
    if not isinstance(team_id, str) or not team_id:
        raise ValueError("team_id is required")
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project_id is required")
    label = (
        "Strong Match"
        if assessment.disposition == "strong_match"
        else "Worth Considering"
    )
    strengths = "\n".join(
        f"- {claim.claim} ({claim.profile_evidence_id})"
        for claim in assessment.strengths
    ) or "- None recorded"
    gaps = "\n".join(f"- {gap}" for gap in assessment.gaps) or "- None recorded"
    uncertainties = (
        "\n".join(f"- {item}" for item in assessment.uncertainties)
        or "- None recorded"
    )
    description = (
        f"## Opportunity\n\n"
        f"- Employer: {job.employer}\n"
        f"- Exact title: {job.title}\n"
        f"- Location: {_display(job.location)}\n"
        f"- Workplace model: {_display(job.workplace_model)}\n"
        f"- Travel: {_display(job.travel)}\n"
        f"- Compensation evidence: {_display(job.compensation_evidence)}\n"
        f"- Requisition identity: {_display(job.requisition_id)}\n"
        f"- Source: {job.source}\n"
        f"- Verified: {job.verified_at}\n"
        f"- Posting: {job.posting_url}\n"
        f"- Application: {job.application_url}\n"
        f"- Deadline: {_display(job.deadline)}\n\n"
        f"## Disposition\n\n{label}\n\n"
        f"## Role-to-profile fit\n\n{assessment.role_to_profile_fit}\n\n"
        f"## Evidence-supported strengths\n\n{strengths}\n\n"
        f"## Gaps\n\n{gaps}\n\n"
        f"## Uncertainties\n\n{uncertainties}\n\n"
        f"## Recommended next action\n\n"
        f"Review this verified role and decide whether to request an application packet.\n"
    )
    return LinearIssuePayload(
        candidate_key=candidate_key(job),
        title=f"{job.employer} — {job.title}",
        team_id=team_id,
        project_id=project_id,
        labels=(label,),
        description=description,
        posting_url=job.posting_url,
        application_url=job.application_url,
    )


def verify_issue_readback(
    expected: LinearIssuePayload,
    actual: Mapping[str, object],
) -> DeliveryReceipt:
    comparisons = {
        "title": expected.title,
        "team_id": expected.team_id,
        "project_id": expected.project_id,
        "labels": list(expected.labels),
        "description": expected.description,
        "posting_url": expected.posting_url,
        "application_url": expected.application_url,
    }
    mismatches = [
        name for name, expected_value in comparisons.items()
        if actual.get(name) != expected_value
    ]
    issue_id = actual.get("issue_id")
    if mismatches or not isinstance(issue_id, str) or not issue_id:
        detail = ", ".join(mismatches) or "issue_id"
        raise DeliveryVerificationError(f"Linear readback mismatch: {detail}")
    return DeliveryReceipt(
        candidate_key=expected.candidate_key,
        issue_id=issue_id,
        verified=True,
        body_hash=expected.body_hash,
    )


def record_delivery(
    state: DiscoveryState,
    receipt: DeliveryReceipt,
) -> DiscoveryState:
    if not receipt.verified:
        raise DeliveryVerificationError("delivery receipt is not verified")
    deliveries = dict(state.deliveries)
    existing = deliveries.get(receipt.candidate_key)
    if existing and existing != receipt.issue_id:
        raise DeliveryVerificationError("candidate already has another Linear issue")
    deliveries[receipt.candidate_key] = receipt.issue_id
    return replace(state, deliveries=deliveries)
