"""Independent source checkpoints and stable review-batch identifiers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path
import re
from typing import Mapping

from .atomic import atomic_write_json, load_json
from .contracts import WorkspacePaths
from .job_store import workspace_lock_if_needed as workspace_lock
from .timestamps import TimestampError, parse_instant


@dataclass(frozen=True)
class SourceCheckpoint:
    last_successful_at: str | None
    seen_records: tuple[str, ...]
    cursor: str | None


@dataclass(frozen=True)
class SourceResult:
    success: bool
    completed_at: str
    seen_records: tuple[str, ...]
    cursor: str | None
    intake_ids: tuple[str, ...] = ()
    coverage_scope_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiscoveryState:
    sources: Mapping[str, SourceCheckpoint] = field(default_factory=dict)
    stable_review_batch: str | None = None
    canonical_jobs: Mapping[str, str] = field(default_factory=dict)


class DiscoveryStateError(ValueError):
    pass


_JOB_ID = re.compile(r"JOB-[0-9]{6}")


def stable_review_batch(keys: tuple[str, ...]) -> str | None:
    if not keys:
        return None
    ordered = "\n".join(sorted(set(keys))).encode("utf-8")
    return hashlib.sha256(ordered).hexdigest()


def complete_source(
    state: DiscoveryState,
    source: str,
    result: SourceResult,
) -> DiscoveryState:
    if not result.success:
        return state
    sources = dict(state.sources)
    sources[source] = SourceCheckpoint(
        last_successful_at=result.completed_at,
        seen_records=tuple(dict.fromkeys(result.seen_records)),
        cursor=result.cursor,
    )
    return replace(state, sources=sources)


def save_discovery_state(path: Path, state: DiscoveryState) -> None:
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "sources": {
                name: {
                    "last_successful_at": checkpoint.last_successful_at,
                    "seen_records": list(checkpoint.seen_records),
                    "cursor": checkpoint.cursor,
                }
                for name, checkpoint in sorted(state.sources.items())
            },
            "stable_review_batch": state.stable_review_batch,
            "canonical_jobs": dict(sorted(state.canonical_jobs.items())),
        },
    )


def load_discovery_state(path: Path) -> DiscoveryState:
    try:
        raw = load_json(path)
        sources_raw = raw["sources"]
        canonical_raw = raw["canonical_jobs"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DiscoveryStateError("discovery state is unreadable") from exc
    if (
        raw.get("schema_version") != 1
        or not isinstance(sources_raw, Mapping)
        or not isinstance(canonical_raw, Mapping)
        or not all(
            isinstance(key, str)
            and isinstance(value, str)
            and _JOB_ID.fullmatch(value)
            for key, value in canonical_raw.items()
        )
    ):
        raise DiscoveryStateError("discovery state is invalid")
    stable = raw.get("stable_review_batch")
    if stable is not None and not isinstance(stable, str):
        raise DiscoveryStateError("stable review batch is invalid")
    sources: dict[str, SourceCheckpoint] = {}
    for name, value in sources_raw.items():
        if not isinstance(name, str) or not isinstance(value, Mapping):
            raise DiscoveryStateError("source checkpoint is invalid")
        successful = value.get("last_successful_at")
        seen = value.get("seen_records")
        cursor = value.get("cursor")
        if (
            successful is not None
            and not isinstance(successful, str)
            or not isinstance(seen, list)
            or not all(isinstance(item, str) for item in seen)
            or cursor is not None
            and not isinstance(cursor, str)
        ):
            raise DiscoveryStateError("source checkpoint is invalid")
        sources[name] = SourceCheckpoint(
            last_successful_at=successful,
            seen_records=tuple(seen),
            cursor=cursor,
        )
    return DiscoveryState(
        sources=sources,
        stable_review_batch=stable,
        canonical_jobs=dict(canonical_raw),
    )


def merge_discovery_state(
    workspace: WorkspacePaths,
    run_state: DiscoveryState,
    source_results: tuple[tuple[str, SourceResult], ...],
) -> DiscoveryState:
    """Merge one completed run into the latest state without losing other runs."""
    source_names = [source for source, _ in source_results]
    if len(source_names) != len(set(source_names)):
        raise DiscoveryStateError("duplicate_source_results")
    state_path = workspace.state / "discovery-state.json"
    with workspace_lock(workspace):
        from .review_queue import enabled, validate_delivery
        from .retrieval import validate_source_result
        if not enabled(workspace):
            for source, result in source_results:
                validate_source_result(workspace, source, result, now=result.completed_at)
        validate_delivery(workspace, {"source_results": {
                source: {"success": result.success, "completed_at": result.completed_at,
                         "seen_records": result.seen_records, "intake_ids": result.intake_ids,
                         "coverage_scope_ids": result.coverage_scope_ids}
                for source, result in source_results
            }}, now=max((result.completed_at for _, result in source_results if result.success),
                        key=parse_instant, default="1970-01-01T00:00:00+00:00"), require_delivered=True)
        latest = (
            load_discovery_state(state_path)
            if state_path.exists()
            else DiscoveryState()
        )
        canonical_jobs = dict(latest.canonical_jobs)
        for identity, job_id in run_state.canonical_jobs.items():
            existing = canonical_jobs.get(identity)
            if existing is not None and existing != job_id:
                raise DiscoveryStateError(
                    "canonical discovery identity maps to conflicting job IDs"
                )
            canonical_jobs[identity] = job_id
        merged = replace(
            latest,
            stable_review_batch=(
                run_state.stable_review_batch
                if run_state.stable_review_batch is not None
                else latest.stable_review_batch
            ),
            canonical_jobs=canonical_jobs,
        )
        for source, result in source_results:
            checkpoint = merged.sources.get(source)
            if result.success:
                try:
                    completed_at = parse_instant(result.completed_at)
                    previous_at = (
                        parse_instant(checkpoint.last_successful_at)
                        if checkpoint is not None
                        and checkpoint.last_successful_at is not None
                        else None
                    )
                except TimestampError as exc:
                    raise DiscoveryStateError(
                        "source checkpoint timestamps must be timezone-aware ISO 8601"
                    ) from exc
                if previous_at is not None and previous_at > completed_at:
                    continue
            merged = complete_source(merged, source, result)
        save_discovery_state(state_path, merged)
        return merged
