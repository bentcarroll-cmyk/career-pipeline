"""Normalize a saved Greenhouse job-board response."""

from __future__ import annotations

from typing import Any, Mapping

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
        raise ValueError("Greenhouse normalization requires employer context")
    records = snapshot.records.get("jobs", [])
    jobs: list[CandidateJob] = []
    for raw in records if isinstance(records, list) else []:
        if not isinstance(raw, Mapping):
            continue
        location_raw = raw.get("location")
        location = (
            as_optional(location_raw.get("name"))
            if isinstance(location_raw, Mapping)
            else as_optional(location_raw)
        )
        workplace = as_optional(raw.get("workplace_model"))
        travel = as_optional(raw.get("travel"))
        compensation = as_optional(raw.get("compensation"))
        posting_url = str(raw.get("absolute_url") or "")
        application_url = str(raw.get("application_url") or posting_url)
        jobs.append(
            CandidateJob(
                source=snapshot.source,
                source_record_id=str(raw.get("id") or ""),
                requisition_id=as_optional(raw.get("requisition_id")),
                employer=employer,
                title=str(raw.get("title") or ""),
                responsibilities=responsibilities(raw.get("content")),
                location=location,
                workplace_model=workplace,
                travel=travel,
                compensation_evidence=compensation,
                posting_url=posting_url,
                application_url=application_url,
                team=as_optional(raw.get("team")),
                posted_at=as_optional(raw.get("created_at")),
                updated_at=as_optional(raw.get("updated_at")),
                deadline=as_optional(raw.get("deadline")),
                verified_at=snapshot.fetched_at,
                verification_status="source_snapshot",
                raw_field_hash=record_hash(raw),
                uncertainties=uncertainty_fields(workplace, travel, compensation),
            )
        )
    return jobs
