"""Resumable onboarding state and connector decisions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping, Sequence


STAGES = (
    "privacy",
    "workspace",
    "linear",
    "optional_connectors",
    "resume",
    "interview",
    "profile",
    "packet_defaults",
    "schedule",
    "readiness",
    "active",
)
CONNECTORS = (
    "linear",
    "indeed",
    "linkedin",
    "firecrawl",
    "browser",
    "notion",
    "github",
    "gmail",
    "google-calendar",
    "google-drive",
    "usajobs",
)


class InvalidTransition(ValueError):
    pass


@dataclass(frozen=True)
class ConnectorStatus:
    decision: str
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class OnboardingState:
    stage: str = "privacy"
    completed: tuple[str, ...] = ()
    connectors: Mapping[str, ConnectorStatus] = field(default_factory=dict)
    profile_hash: str | None = None
    criteria_hash: str | None = None

    @classmethod
    def at(cls, stage: str) -> "OnboardingState":
        if stage not in STAGES:
            raise ValueError(f"unknown onboarding stage: {stage}")
        return cls(stage=stage, completed=STAGES[: STAGES.index(stage)])


def record_connector_decision(
    state: OnboardingState,
    connector: str,
    decision: str,
    capabilities: Sequence[str],
    expected_capabilities: Sequence[str] = (),
) -> OnboardingState:
    if connector not in CONNECTORS:
        raise ValueError(f"unknown connector: {connector}")
    if decision not in {"connected", "declined", "unavailable"}:
        raise ValueError(f"unknown connector decision: {decision}")
    observed = tuple(sorted(set(capabilities)))
    if decision == "connected" and not set(expected_capabilities).issubset(observed):
        decision = "unavailable"
    updated = dict(state.connectors)
    updated[connector] = ConnectorStatus(decision=decision, capabilities=observed)
    return replace(state, connectors=updated)


def record_profile_approval(
    state: OnboardingState,
    profile_hash: str,
    criteria_hash: str,
) -> OnboardingState:
    if not profile_hash or not criteria_hash:
        raise ValueError("approval hashes must be non-empty")
    return replace(state, profile_hash=profile_hash, criteria_hash=criteria_hash)


def advance_onboarding(
    state: OnboardingState,
    completed_stage: str,
    receipt: Mapping[str, object],
) -> OnboardingState:
    if completed_stage not in STAGES:
        raise InvalidTransition(f"unknown stage: {completed_stage}")
    current_index = STAGES.index(state.stage)
    requested_index = STAGES.index(completed_stage)
    if completed_stage == "active":
        linear = state.connectors.get("linear")
        if (
            linear is None
            or linear.decision != "connected"
            or not state.profile_hash
            or not state.criteria_hash
            or not receipt.get("ready")
        ):
            raise InvalidTransition("activation prerequisites are not satisfied")
    if requested_index < current_index:
        raise InvalidTransition("onboarding stages cannot move backward")
    if requested_index > current_index + 1:
        raise InvalidTransition("onboarding stages cannot be skipped")
    completed = tuple(dict.fromkeys((*state.completed, state.stage)))
    return replace(state, stage=completed_stage, completed=completed)
