"""Normalize a saved Ashby job-board response."""

from __future__ import annotations

from typing import Mapping

from .base import (
    CandidateJob,
    SourceSnapshot,
    as_optional,
    record_hash,
    responsibilities,
    uncertainty_fields,
)


def normalize(snapshot: SourceSnapshot) -> list[CandidateJob]:
    if not snapshot.success or not isinstance(snapshot.records, Mapping):
        return []
    employer = as_optional(snapshot.records.get("employer")) or as_optional(
        snapshot.employer
    )
    if employer is None:
        raise ValueError("Ashby normalization requires employer context")
    records = snapshot.records.get("jobs", [])
    jobs: list[CandidateJob] = []
    for raw in records if isinstance(records, list) else []:
        if not isinstance(raw, Mapping):
            continue
        workplace = as_optional(raw.get("workplaceType"))
        travel = as_optional(raw.get("travel"))
        compensation = as_optional(raw.get("compensation"))
        jobs.append(
            CandidateJob(
                source=snapshot.source,
                source_record_id=str(raw.get("id") or ""),
                requisition_id=as_optional(raw.get("requisitionId")),
                employer=employer,
                title=str(raw.get("title") or ""),
                responsibilities=responsibilities(
                    raw.get("descriptionPlain") or raw.get("descriptionHtml")
                ),
                location=as_optional(raw.get("location")),
                workplace_model=workplace,
                travel=travel,
                compensation_evidence=compensation,
                posting_url=str(raw.get("jobUrl") or ""),
                application_url=str(raw.get("applyUrl") or raw.get("jobUrl") or ""),
                team=as_optional(raw.get("team")),
                posted_at=as_optional(raw.get("publishedAt")),
                updated_at=as_optional(raw.get("updatedAt")),
                deadline=as_optional(raw.get("deadline")),
                verified_at=snapshot.fetched_at,
                verification_status="source_snapshot",
                raw_field_hash=record_hash(raw),
                uncertainties=uncertainty_fields(workplace, travel, compensation),
            )
        )
    return jobs
