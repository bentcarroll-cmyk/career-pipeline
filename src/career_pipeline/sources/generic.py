"""Normalize canonical snapshots from optional broad-source connectors."""

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
    if not snapshot.success or not isinstance(snapshot.records, list):
        return []
    jobs: list[CandidateJob] = []
    for raw in snapshot.records:
        if not isinstance(raw, Mapping):
            continue
        workplace = as_optional(raw.get("workplace_model"))
        travel = as_optional(raw.get("travel"))
        compensation = as_optional(raw.get("compensation_evidence"))
        jobs.append(
            CandidateJob(
                source=snapshot.source,
                source_record_id=str(raw.get("source_record_id") or ""),
                requisition_id=as_optional(raw.get("requisition_id")),
                employer=str(raw.get("employer") or ""),
                title=str(raw.get("title") or ""),
                responsibilities=responsibilities(raw.get("responsibilities")),
                location=as_optional(raw.get("location")),
                workplace_model=workplace,
                travel=travel,
                compensation_evidence=compensation,
                posting_url=str(raw.get("posting_url") or ""),
                application_url=str(
                    raw.get("application_url") or raw.get("posting_url") or ""
                ),
                team=as_optional(raw.get("team")),
                posted_at=as_optional(raw.get("posted_at")),
                updated_at=as_optional(raw.get("updated_at")),
                deadline=as_optional(raw.get("deadline")),
                verified_at=snapshot.fetched_at,
                verification_status=str(
                    raw.get("verification_status") or "source_snapshot"
                ),
                raw_field_hash=record_hash(raw),
                uncertainties=uncertainty_fields(workplace, travel, compensation),
            )
        )
    return jobs
