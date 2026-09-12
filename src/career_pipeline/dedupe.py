"""Stable requisition identity and conservative fallback deduplication."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping

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
class OpportunityIdentity:
    requisition: str | None
    fallback: str


@dataclass(frozen=True)
class IdentityResolution:
    matched_ids: tuple[str, ...] = ()
    ambiguous_ids: tuple[str, ...] = ()

    @property
    def ambiguous(self) -> bool:
        return bool(self.ambiguous_ids)


def identity_from_fields(
    employer: str,
    requisition_id: str | None,
    title: str,
    location: str | None,
    team: str | None,
) -> OpportunityIdentity:
    return OpportunityIdentity(
        requisition_identity(employer, requisition_id),
        fallback_identity(employer, title, location, team),
    )


def candidate_identity(job: CandidateJob) -> OpportunityIdentity:
    return identity_from_fields(
        job.employer, job.requisition_id, job.title, job.location, job.team
    )


def resolve_identity(
    wanted: OpportunityIdentity,
    existing: Mapping[str, OpportunityIdentity],
) -> IdentityResolution:
    if wanted.requisition is not None:
        exact = tuple(
            job_id
            for job_id, identity in existing.items()
            if identity.requisition == wanted.requisition
        )
        if exact:
            return (
                IdentityResolution(matched_ids=exact)
                if len(exact) == 1
                else IdentityResolution(ambiguous_ids=exact)
            )
        fallback = tuple(
            job_id
            for job_id, identity in existing.items()
            if identity.requisition is None and identity.fallback == wanted.fallback
        )
    else:
        fallback = tuple(
            job_id
            for job_id, identity in existing.items()
            if identity.fallback == wanted.fallback
        )
    if len(fallback) == 1:
        return IdentityResolution(matched_ids=fallback)
    if fallback:
        return IdentityResolution(ambiguous_ids=fallback)
    return IdentityResolution()


@dataclass(frozen=True)
class DiscoveryPartition:
    novel: tuple[CandidateJob, ...]
    duplicates: tuple[CandidateJob, ...]


def partition_candidates(
    candidates: Iterable[CandidateJob],
    existing: Iterable[CandidateJob],
) -> DiscoveryPartition:
    seen = {
        f"existing-{index}": candidate_identity(job)
        for index, job in enumerate(existing)
    }
    novel: list[CandidateJob] = []
    duplicates: list[CandidateJob] = []
    for job in candidates:
        resolution = resolve_identity(candidate_identity(job), seen)
        if resolution.matched_ids or resolution.ambiguous:
            duplicates.append(job)
            continue
        seen[f"candidate-{len(seen)}"] = candidate_identity(job)
        novel.append(job)
    return DiscoveryPartition(tuple(novel), tuple(duplicates))
