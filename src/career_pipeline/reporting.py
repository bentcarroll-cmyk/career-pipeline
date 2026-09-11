"""Quiet-by-default discovery reporting."""

from __future__ import annotations

from typing import Sequence


def discovery_report(
    new_job_ids: Sequence[str],
    meaningful_changes: Sequence[str],
    failure_codes: Sequence[str],
    previously_reported_failures: Sequence[str],
) -> str | None:
    new_failures = [
        code for code in failure_codes if code not in set(previously_reported_failures)
    ]
    if not new_job_ids and not meaningful_changes and not new_failures:
        return None
    parts: list[str] = []
    if new_job_ids:
        parts.append("New matches: " + ", ".join(new_job_ids))
    if meaningful_changes:
        parts.append("Meaningful changes: " + ", ".join(meaningful_changes))
    if new_failures:
        parts.append("Actionable source failures: " + ", ".join(new_failures))
    return "\n".join(parts)
