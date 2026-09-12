"""Timezone-aware timestamp comparison for persisted workflow state."""

from __future__ import annotations

from datetime import datetime, timezone


class TimestampError(ValueError):
    pass


def parse_instant(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise TimestampError("timestamp must be a non-empty string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise TimestampError("timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TimestampError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)
