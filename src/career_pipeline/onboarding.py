"""Resumable onboarding state and connector decisions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping, Sequence

from .atomic import atomic_write_json, load_json
from .capabilities import CONNECTORS


STAGES = (
    "privacy",
    "workspace",
    "connectors",
    "resume",
    "interview",
    "profile",
    "packet_defaults",
    "schedule",
    "readiness",
    "active",
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
    receipts: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
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
        if (
            set(CONNECTORS).difference(state.connectors)
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
    receipts = dict(state.receipts)
    receipts[state.stage] = dict(receipt)
    return replace(
        state,
        stage=completed_stage,
        completed=completed,
        receipts=receipts,
    )


def save_onboarding_state(path: Path, state: OnboardingState) -> None:
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "stage": state.stage,
            "completed": list(state.completed),
            "connectors": {
                name: {
                    "decision": status.decision,
                    "capabilities": list(status.capabilities),
                }
                for name, status in sorted(state.connectors.items())
            },
            "receipts": {
                name: dict(receipt)
                for name, receipt in sorted(state.receipts.items())
            },
            "profile_hash": state.profile_hash,
            "criteria_hash": state.criteria_hash,
        },
    )


def load_onboarding_state(path: Path) -> OnboardingState:
    raw = load_json(path)
    connectors = {
        name: ConnectorStatus(
            decision=str(value["decision"]),
            capabilities=tuple(value.get("capabilities", ())),
        )
        for name, value in raw.get("connectors", {}).items()
    }
    return OnboardingState(
        stage=str(raw["stage"]),
        completed=tuple(raw.get("completed", ())),
        connectors=connectors,
        receipts={
            name: dict(receipt)
            for name, receipt in raw.get("receipts", {}).items()
        },
        profile_hash=raw.get("profile_hash"),
        criteria_hash=raw.get("criteria_hash"),
    )
