"""Normalize a saved Lever postings response."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, Sequence

from .base import (
    CandidateJob,
    SourceSnapshot,
    as_optional,
    record_hash,
    responsibilities,
    uncertainty_fields,
)


def _timestamp(value: object) -> str | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
    return as_optional(value)


def normalize(snapshot: SourceSnapshot) -> list[CandidateJob]:
    if not snapshot.success or not isinstance(snapshot.records, list):
        return []
    employer = as_optional(snapshot.employer)
    board = as_optional(snapshot.board)
    if employer is None or board is None:
        raise ValueError("Lever normalization requires employer and board context")
    jobs: list[CandidateJob] = []
    for raw in snapshot.records:
        if not isinstance(raw, Mapping):
            continue
        categories = raw.get("categories")
        categories = categories if isinstance(categories, Mapping) else {}
        workplace = as_optional(raw.get("workplaceType"))
        travel = as_optional(raw.get("travel"))
        compensation = as_optional(raw.get("salaryRange"))
        source_record_id = str(raw.get("id") or "")
        requisition = as_optional(raw.get("requisition"))
        sections = list(
            responsibilities(raw.get("descriptionPlain") or raw.get("description"))
        )
        raw_lists = raw.get("lists")
        if isinstance(raw_lists, Sequence) and not isinstance(raw_lists, (str, bytes)):
            for section in raw_lists:
                if not isinstance(section, Mapping):
                    continue
                name = as_optional(section.get("text"))
                content = as_optional(section.get("content"))
                if content:
                    sections.append(f"{name}: {content}" if name else content)
        sections.extend(
            responsibilities(raw.get("additionalPlain") or raw.get("additional"))
        )
        jobs.append(
            CandidateJob(
                source=snapshot.source,
                source_record_id=source_record_id,
                requisition_id=(
                    requisition or f"lever:{board.casefold()}:{source_record_id}"
                ),
                employer=employer,
                title=str(raw.get("text") or ""),
                responsibilities=tuple(sections),
                location=as_optional(categories.get("location")),
                workplace_model=workplace,
                travel=travel,
                compensation_evidence=compensation,
                posting_url=str(raw.get("hostedUrl") or ""),
                application_url=str(raw.get("applyUrl") or raw.get("hostedUrl") or ""),
                team=as_optional(categories.get("team")),
                posted_at=_timestamp(raw.get("createdAt")),
                updated_at=as_optional(raw.get("updatedAt")),
                deadline=as_optional(raw.get("deadline")),
                verified_at=snapshot.fetched_at,
                verification_status="source_snapshot",
                raw_field_hash=record_hash(raw),
                uncertainties=uncertainty_fields(workplace, travel, compensation),
            )
        )
    return jobs
