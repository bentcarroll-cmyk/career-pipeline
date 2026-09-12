"""Shared source contracts and normalization helpers."""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class SourceSnapshot:
    source: str
    fetched_at: str
    records: object
    cursor: str | None = None
    success: bool = True
    employer: str | None = None
    board: str | None = None


@dataclass(frozen=True)
class CandidateJob:
    source: str
    source_record_id: str
    requisition_id: str | None
    employer: str
    title: str
    responsibilities: tuple[str, ...]
    location: str | None
    workplace_model: str | None
    travel: str | None
    compensation_evidence: str | None
    posting_url: str
    application_url: str
    team: str | None
    posted_at: str | None
    updated_at: str | None
    deadline: str | None
    verified_at: str
    verification_status: str
    raw_field_hash: str
    uncertainties: tuple[str, ...]


_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def clean_text(value: object) -> str:
    text = html.unescape(_TAG.sub(" ", str(value or "")))
    return _SPACE.sub(" ", text).strip()


def as_optional(value: object) -> str | None:
    cleaned = clean_text(value)
    return cleaned or None


def responsibilities(value: object) -> tuple[str, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(item for item in (clean_text(part) for part in value) if item)
    cleaned = clean_text(value)
    return (cleaned,) if cleaned else ()


def record_hash(record: Mapping[str, Any]) -> str:
    payload = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def uncertainty_fields(
    workplace_model: str | None,
    travel: str | None,
    compensation_evidence: str | None,
) -> tuple[str, ...]:
    values = {
        "workplace_model": workplace_model,
        "travel": travel,
        "compensation": compensation_evidence,
    }
    return tuple(name for name, value in values.items() if value is None)
