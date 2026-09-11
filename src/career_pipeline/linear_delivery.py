"""Linear payload shaping for explicit optional exports of canonical local jobs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping

from .contracts import WorkspacePaths
from .exports import ExportReceipt, ExportRequestError
from .job_store import JobStoreError, read_job


class ExportVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class LinearExportPayload:
    job_id: str
    title: str
    team_id: str
    project_id: str
    labels: tuple[str, ...]
    description: str
    posting_url: str
    application_url: str

    @property
    def content_hash(self) -> str:
        value = {
            "job_id": self.job_id,
            "title": self.title,
            "team_id": self.team_id,
            "project_id": self.project_id,
            "labels": self.labels,
            "description": self.description,
            "posting_url": self.posting_url,
            "application_url": self.application_url,
        }
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

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


def _display(value: object) -> str:
    return str(value) if value else "Not stated; needs confirmation"


def _bullets(value: object, empty: str) -> str:
    if not isinstance(value, list) or not value:
        return f"- {empty}"
    lines: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            claim = item.get("claim")
            evidence_id = item.get("profile_evidence_id")
            lines.append(f"- {claim} ({evidence_id})")
        else:
            lines.append(f"- {item}")
    return "\n".join(lines)


def build_linear_export_payload(
    workspace: WorkspacePaths,
    job_id: str,
    config: Mapping[str, object],
    *,
    explicit_request: bool,
) -> LinearExportPayload:
    if not explicit_request:
        raise ExportRequestError("Linear export requires a current explicit request")
    try:
        job = read_job(workspace, job_id)
    except JobStoreError as exc:
        raise ExportRequestError("Linear export requires an existing canonical job") from exc
    team_id = config.get("team_id")
    project_id = config.get("project_id")
    if not isinstance(team_id, str) or not team_id:
        raise ExportRequestError("Linear team_id is required for this export")
    if not isinstance(project_id, str) or not project_id:
        raise ExportRequestError("Linear project_id is required for this export")
    label = (
        "Strong Match"
        if job["disposition"] == "strong_match"
        else "Worth Considering"
    )
    description = (
        f"## Local identity\n\n{job_id}\n\n"
        f"## Opportunity\n\n"
        f"- Employer: {job['employer']}\n"
        f"- Exact title: {job['title']}\n"
        f"- Location: {_display(job.get('location'))}\n"
        f"- Workplace model: {_display(job.get('workplace_model'))}\n"
        f"- Travel: {_display(job.get('travel'))}\n"
        f"- Compensation evidence: {_display(job.get('compensation_evidence'))}\n"
        f"- Requisition identity: {_display(job.get('requisition_id'))}\n"
        f"- Source: {job['source']}\n"
        f"- Verified: {job['verified_at']}\n"
        f"- Posting: {job['posting_url']}\n"
        f"- Application: {job['application_url']}\n"
        f"- Deadline: {_display(job.get('deadline'))}\n\n"
        f"## Disposition\n\n{label}\n\n"
        f"## Role-to-profile fit\n\n{job['role_to_profile_fit']}\n\n"
        f"## Evidence-supported strengths\n\n"
        f"{_bullets(job.get('strengths'), 'None recorded')}\n\n"
        f"## Gaps\n\n{_bullets(job.get('gaps'), 'None recorded')}\n\n"
        f"## Uncertainties\n\n"
        f"{_bullets(job.get('uncertainties'), 'None recorded')}\n\n"
        f"## Local status\n\n{job['status']}\n"
    )
    return LinearExportPayload(
        job_id=job_id,
        title=f"[{job_id}] {job['employer']} — {job['title']}",
        team_id=team_id,
        project_id=project_id,
        labels=(label,),
        description=description,
        posting_url=str(job["posting_url"]),
        application_url=str(job["application_url"]),
    )


def verify_linear_export_readback(
    expected: LinearExportPayload,
    actual: Mapping[str, object],
    *,
    exported_at: str,
    artifact_hashes: Mapping[str, str] | None = None,
) -> ExportReceipt:
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
        name
        for name, expected_value in comparisons.items()
        if actual.get(name) != expected_value
    ]
    issue_id = actual.get("issue_id")
    if mismatches or not isinstance(issue_id, str) or not issue_id or not exported_at:
        detail = ", ".join(mismatches) or "issue_id or exported_at"
        raise ExportVerificationError(f"Linear export readback mismatch: {detail}")
    return ExportReceipt(
        destination_kind="linear",
        destination_id=issue_id,
        job_id=expected.job_id,
        exported_at=exported_at,
        content_hash=expected.content_hash,
        artifact_hashes=dict(artifact_hashes or {}),
        verified=True,
    )
