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
    return requisition_identity(job.employer, job.requisition_id)


def requisition_identity(employer: str, requisition_id: str | None) -> str | None:
    if not requisition_id:
        return None
    return f"req:{_normalize(employer)}:{_normalize(requisition_id)}"


def fallback_fingerprint(job: CandidateJob) -> str:
    return fallback_identity(job.employer, job.title, job.location, job.team)


def fallback_identity(
    employer: str,
    title: str,
    location: str | None,
    team: str | None,
) -> str:
    values = tuple(_normalize(value) for value in (employer, title, location, team))
    return "fp:" + hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()


def identity_keys(job: CandidateJob) -> tuple[str, ...]:
    fallback = fallback_fingerprint(job)
    requisition = requisition_key(job)
    return (requisition, fallback) if requisition else (fallback,)


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
