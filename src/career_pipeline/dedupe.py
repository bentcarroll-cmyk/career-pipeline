"""Stable requisition identity and conservative fallback deduplication."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from .sources.base import CandidateJob


_SPACE = re.compile(r"\s+")


def _normalize(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold().strip()
    return _SPACE.sub(" ", text)


def requisition_key(job: CandidateJob) -> str | None:
    if not job.requisition_id:
        return None
    return f"req:{_normalize(job.employer)}:{_normalize(job.requisition_id)}"


def fallback_fingerprint(job: CandidateJob) -> str:
    values = (
        _normalize(job.employer),
        _normalize(job.title),
        _normalize(job.location),
        _normalize(job.team),
    )
    return "fp:" + hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()


def candidate_key(job: CandidateJob) -> str:
    return requisition_key(job) or fallback_fingerprint(job)


@dataclass(frozen=True)
class DiscoveryPartition:
    novel: tuple[CandidateJob, ...]
    duplicates: tuple[CandidateJob, ...]


def partition_candidates(
    candidates: Iterable[CandidateJob],
    existing: Iterable[CandidateJob],
) -> DiscoveryPartition:
    seen = {candidate_key(job) for job in existing}
    novel: list[CandidateJob] = []
    duplicates: list[CandidateJob] = []
    for job in candidates:
        key = candidate_key(job)
        if key in seen:
            duplicates.append(job)
            continue
        seen.add(key)
        novel.append(job)
    return DiscoveryPartition(tuple(novel), tuple(duplicates))
