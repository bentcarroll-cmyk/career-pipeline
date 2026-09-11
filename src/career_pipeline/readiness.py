"""Activation readiness checks with stable remediation codes."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .capabilities import LINEAR_REQUIRED_ACTIONS, OPTIONAL_CONNECTORS
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
        if not os.access(root, os.W_OK):
            failures.append("workspace_unwritable")
        profile = root / "Profile" / "Career_Profile.md"
        criteria = root / "Profile" / "Search_Criteria.md"
        preferences = root / "Profile" / "Writing_Preferences.md"
        resumes = list((root / "Sources").glob("Resume_Original.*"))
        if not profile.is_file() or not criteria.is_file() or not preferences.is_file() or len(resumes) != 1:
            failures.append("required_files_missing")
        else:
            profile_hash = hashlib.sha256(profile.read_bytes()).hexdigest()
            criteria_hash = hashlib.sha256(criteria.read_bytes()).hexdigest()
            if (
                onboarding.profile_hash != profile_hash
                or onboarding.criteria_hash != criteria_hash
            ):
                failures.append("approved_files_changed")

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
    linear_destination = config.get("linear")
    if (
        not isinstance(linear_destination, Mapping)
        or any(
            not isinstance(linear_destination.get(field), str)
            or not linear_destination.get(field)
            for field in ("workspace_id", "team_id", "project_id")
        )
    ):
        failures.append("linear_destination_missing")
    if not onboarding.profile_hash or not onboarding.criteria_hash:
        failures.append("profile_not_approved")
    if any(name not in onboarding.connectors for name in OPTIONAL_CONNECTORS):
        failures.append("connector_decisions_incomplete")
    sources = config.get("enabled_sources")
    if not isinstance(sources, list) or not sources:
        failures.append("no_discovery_source")
    packet_defaults = config.get("packet_defaults")
    if (
        not isinstance(packet_defaults, Mapping)
        or packet_defaults.get("resume_pages") != 2
        or not isinstance(packet_defaults.get("cover_letter_enabled"), bool)
        or packet_defaults.get("cover_letter_pages")
        != (1 if packet_defaults.get("cover_letter_enabled") else 0)
    ):
        failures.append("packet_defaults_invalid")
    return ReadinessReport(tuple(dict.fromkeys(failures)))
