"""Independent source checkpoints and stable review-batch identifiers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import Mapping


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
