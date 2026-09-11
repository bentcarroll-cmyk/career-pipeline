"""Allow only the scheduled workflows approved by the product design."""

from __future__ import annotations

from typing import Mapping

from .onboarding import OnboardingState


class UnsupportedAutomation(ValueError):
    pass


def render_automation(kind: str, config: Mapping[str, object]) -> str:
    if kind not in {"discovery", "lifecycle"}:
        raise UnsupportedAutomation(f"unsupported automation kind: {kind}")
    config_path = config.get("workspace_config")
    timezone = config.get("timezone")
    if not isinstance(config_path, str) or not config_path:
        raise ValueError("workspace_config is required")
    if not isinstance(timezone, str) or not timezone:
        raise ValueError("timezone is required")
    if kind == "discovery":
        return (
            f"Use $discover-jobs with the approved configuration at {config_path}. "
            "Verify enabled sources and the configured Linear destination, preserve "
            "independent source checkpoints, and report only new matches, meaningful "
            "changes, or actionable failures. Stay quiet when nothing actionable changes. "
            f"Interpret the cadence in timezone {timezone}."
        )
    if kind == "lifecycle":
        return (
            f"Use the approved lifecycle rules referenced by {config_path}. Read only "
            "enabled job-related Gmail or Calendar evidence, update the exact Linear "
            "ticket only for an unambiguous status, and retain only a minimal receipt. "
            "Stay quiet when evidence is unchanged or non-actionable. Never send, reply, "
            f"accept, or create an event. Interpret the cadence in timezone {timezone}."
        )
    raise AssertionError("allowed automation kind was not rendered")


def automation_allowed(kind: str, ready: bool) -> bool:
    if kind not in {"discovery", "lifecycle"}:
        raise UnsupportedAutomation(f"unsupported automation kind: {kind}")
    return ready


def default_discovery_schedule(timezone: str) -> dict[str, object]:
    if not timezone:
        raise ValueError("timezone is required")
    return {
        "frequency": "weekday",
        "weekdays": ["MO", "TU", "WE", "TH", "FR"],
        "runs_per_day": 2,
        "timezone": timezone,
    }


def lifecycle_available(state: OnboardingState) -> bool:
    return any(
        state.connectors.get(name) is not None
        and state.connectors[name].decision == "connected"
        for name in ("gmail", "google-calendar")
    )
