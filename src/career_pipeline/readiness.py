"""Activation readiness checks with stable remediation codes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .capabilities import LINEAR_REQUIRED_ACTIONS
from .onboarding import OnboardingState


@dataclass(frozen=True)
class ReadinessReport:
    failure_codes: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.failure_codes


def check_readiness(
    config: Mapping[str, object],
    onboarding: OnboardingState,
) -> ReadinessReport:
    failures: list[str] = []
    root_value = config.get("workspace_root")
    if not isinstance(root_value, str) or not Path(root_value).is_dir():
        failures.append("workspace_unavailable")
    else:
        root = Path(root_value)
        for relative in ("Profile", "Sources", "Applications", "Runs", "State"):
            if not (root / relative).is_dir():
                failures.append("workspace_incomplete")
                break

    timezone = config.get("timezone")
    try:
        if not isinstance(timezone, str) or not timezone:
            raise ZoneInfoNotFoundError
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        failures.append("timezone_invalid")

    linear = onboarding.connectors.get("linear")
    if (
        linear is None
        or linear.decision != "connected"
        or not LINEAR_REQUIRED_ACTIONS.issubset(linear.capabilities)
    ):
        failures.append("linear_required")
    if not onboarding.profile_hash or not onboarding.criteria_hash:
        failures.append("profile_not_approved")
    sources = config.get("enabled_sources")
    if not isinstance(sources, list) or not sources:
        failures.append("no_discovery_source")
    return ReadinessReport(tuple(dict.fromkeys(failures)))
