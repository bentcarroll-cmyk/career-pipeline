"""Explicit request boundary for packet selections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .contracts import WorkspacePaths
from .indexes import load_indexes
from .job_store import JobStoreError, read_job, update_job_status


class SelectionError(ValueError):
    pass


@dataclass(frozen=True)
class PacketSelection:
    job_ids: tuple[str, ...]
    per_role_instructions: Mapping[str, str]

    @property
    def ticket_ids(self) -> tuple[str, ...]:
        return self.job_ids


def selection_from_request(
    job_ids: Sequence[str],
    per_role_instructions: Mapping[str, str],
    *,
    explicit_request: bool,
    workspace: WorkspacePaths,
) -> PacketSelection:
    if not explicit_request:
        raise SelectionError("packet preparation requires an explicit current request")
    ordered = tuple(dict.fromkeys(job.strip() for job in job_ids if job.strip()))
    if not ordered:
        raise SelectionError("at least one exact ticket ID is required")
    unknown = set(per_role_instructions).difference(ordered)
    if unknown:
        raise SelectionError("role instructions reference an unselected job")
    try:
        for job_id in ordered:
            read_job(workspace, job_id)
    except JobStoreError as exc:
        raise SelectionError("every selected job must exist in the canonical store") from exc
    return PacketSelection(ordered, dict(per_role_instructions))


def compare_jobs(
    workspace: WorkspacePaths,
    job_ids: Sequence[str],
) -> tuple[dict[str, object], ...]:
    ordered = tuple(dict.fromkeys(job_ids))
    return tuple(read_job(workspace, job_id) for job_id in ordered)


def mark_not_pursuing(
    workspace: WorkspacePaths,
    job_id: str,
    *,
    occurred_at: str,
) -> dict[str, object]:
    updated = update_job_status(
        workspace,
        job_id,
        "not_pursuing",
        occurred_at=occurred_at,
    )
    load_indexes(workspace)
    return updated
