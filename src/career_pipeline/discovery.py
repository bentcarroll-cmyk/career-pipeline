"""Persist reviewed discovery results into canonical local job folders."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from .atomic import atomic_write_json
from .checkpoints import DiscoveryState, stable_review_batch
from .contracts import WorkspacePaths
from .dedupe import candidate_key
from .evaluation import JobAssessment
from .indexes import load_indexes, rebuild_indexes
from .job_store import (
    DuplicateJobError,
    create_job,
    read_job,
    reverify_job,
    workspace_lock,
)
from .sources.base import CandidateJob


@dataclass(frozen=True)
class ReviewedJob:
    candidate: CandidateJob
    assessment: JobAssessment
    posting_markdown: str
    assessment_markdown: str


@dataclass(frozen=True)
class DiscoveryOutcome:
    state: DiscoveryState
    created_job_ids: tuple[str, ...]
    duplicate_keys: tuple[str, ...]
    non_match_keys: tuple[str, ...]
    meaningful_change_job_ids: tuple[str, ...]
    run_evidence: Path


def _run_evidence_path(
    workspace: WorkspacePaths,
    occurred_at: str,
    reviewed: Sequence[ReviewedJob],
) -> Path:
    digest = hashlib.sha256()
    digest.update(occurred_at.encode("utf-8"))
    for item in reviewed:
        digest.update(candidate_key(item.candidate).encode("utf-8"))
        digest.update(b"\n")
    return workspace.runs / "discovery" / f"run-{digest.hexdigest()[:16]}.json"


def deliver_reviewed_jobs(
    workspace: WorkspacePaths,
    state: DiscoveryState,
    reviewed: Sequence[ReviewedJob],
    *,
    occurred_at: str,
) -> DiscoveryOutcome:
    if not occurred_at:
        raise ValueError("occurred_at is required")
    baseline = load_indexes(workspace)
    raw_identities = baseline.deduplication.get("identities", {})
    identities = raw_identities if isinstance(raw_identities, dict) else {}
    created: list[str] = []
    duplicates: list[str] = []
    non_matches: list[str] = []
    meaningful_changes: list[str] = []
    canonical_jobs = dict(state.canonical_jobs)
    for item in reviewed:
        key = candidate_key(item.candidate)
        if item.assessment.disposition == "non_match":
            non_matches.append(key)
            continue
        if key in identities:
            duplicates.append(key)
            matched = identities[key]
            if isinstance(matched, list) and len(matched) == 1:
                job_id = str(matched[0])
                canonical_jobs[key] = job_id
                existing = read_job(workspace, job_id)
                if existing.get("source") == item.candidate.source:
                    result = reverify_job(
                        workspace,
                        job_id,
                        item.candidate,
                        item.assessment,
                        posting_markdown=item.posting_markdown,
                        assessment_markdown=item.assessment_markdown,
                        occurred_at=occurred_at,
                    )
                    if result.changed:
                        meaningful_changes.append(job_id)
            continue
        try:
            record = create_job(
                workspace,
                item.candidate,
                item.assessment,
                posting_markdown=item.posting_markdown,
                assessment_markdown=item.assessment_markdown,
                occurred_at=occurred_at,
            )
        except DuplicateJobError as exc:
            duplicates.append(key)
            if len(exc.job_ids) == 1:
                job_id = exc.job_ids[0]
                canonical_jobs[key] = job_id
                existing = read_job(workspace, job_id)
                if existing.get("source") == item.candidate.source:
                    result = reverify_job(
                        workspace,
                        job_id,
                        item.candidate,
                        item.assessment,
                        posting_markdown=item.posting_markdown,
                        assessment_markdown=item.assessment_markdown,
                        occurred_at=occurred_at,
                    )
                    if result.changed:
                        meaningful_changes.append(job_id)
            continue
        job_id = str(record["job_id"])
        created.append(job_id)
        canonical_jobs[key] = job_id
    rebuild_indexes(workspace)
    updated_state = replace(
        state,
        stable_review_batch=stable_review_batch(tuple(created)),
        canonical_jobs=canonical_jobs,
    )
    evidence_path = _run_evidence_path(workspace, occurred_at, reviewed)
    with workspace_lock(workspace):
        atomic_write_json(
            evidence_path,
            {
                "schema_version": 1,
                "occurred_at": occurred_at,
                "created_job_ids": created,
                "duplicate_keys": duplicates,
                "non_match_keys": non_matches,
                "meaningful_change_job_ids": meaningful_changes,
            },
        )
    return DiscoveryOutcome(
        state=updated_state,
        created_job_ids=tuple(created),
        duplicate_keys=tuple(duplicates),
        non_match_keys=tuple(non_matches),
        meaningful_change_job_ids=tuple(dict.fromkeys(meaningful_changes)),
        run_evidence=evidence_path,
    )
