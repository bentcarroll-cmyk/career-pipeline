"""Independent source checkpoints and stable review-batch identifiers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path
import re
from typing import Mapping

from .atomic import atomic_write_json, load_json


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
