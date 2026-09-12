"""Resumable onboarding state and connector decisions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping, Sequence

from .atomic import atomic_write_json, load_json
from .capabilities import CONNECTORS, PUBLIC_DISCOVERY_SOURCES


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
QUICK_START_STAGES = (
    "privacy",
    "workspace",
    "resume",
    "focus",
    "profile",
    "packet_defaults",
    "connectors",
    "schedule",
    "readiness",
    "active",
)
CONNECTOR_GROUPS = {
    "job_discovery": ("indeed", "linkedin", "firecrawl", "browser", "usajobs"),
    "career_context": ("notion", "github", "google-drive"),
    "lifecycle_context": ("gmail", "google-calendar"),
    "optional_export": ("linear",),
}
_CONNECTOR_DECISIONS = frozenset(
    {"connected", "declined", "deferred", "unavailable"}
)
_POST_ACTIVATION_ITEMS = frozenset({"connector_configuration", "interview"})


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
    mode: str = "full"
    post_activation: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def at(cls, stage: str) -> "OnboardingState":
        if stage not in STAGES:
            raise ValueError(f"unknown onboarding stage: {stage}")
        return cls(stage=stage, completed=STAGES[: STAGES.index(stage)])

    @classmethod
    def quick_start(cls) -> "OnboardingState":
        return cls(
            mode="quick_start",
            post_activation={
                "connector_configuration": "pending",
                "interview": "pending",
            },
        )


def record_connector_decision(
    state: OnboardingState,
    connector: str,
    decision: str,
    capabilities: Sequence[str],
    expected_capabilities: Sequence[str] = (),
) -> OnboardingState:
    if connector not in CONNECTORS:
        raise ValueError(f"unknown connector: {connector}")
    if decision not in _CONNECTOR_DECISIONS:
        raise ValueError(f"unknown connector decision: {decision}")
    observed = tuple(sorted(set(capabilities)))
    if decision == "connected" and not set(expected_capabilities).issubset(observed):
        decision = "unavailable"
    updated = dict(state.connectors)
    updated[connector] = ConnectorStatus(decision=decision, capabilities=observed)
    return replace(state, connectors=updated)


def record_post_activation_progress(
    state: OnboardingState,
    item: str,
    *,
    completed: bool,
) -> OnboardingState:
    """Persist optional work that a quick start left for later."""

    if state.mode != "quick_start" or state.stage != "active":
        raise InvalidTransition("post-activation progress requires an active quick start")
    if item not in _POST_ACTIVATION_ITEMS:
        raise InvalidTransition("unknown post-activation item")
    if (
        item == "connector_configuration"
        and completed
        and any(status.decision == "deferred" for status in state.connectors.values())
    ):
        raise InvalidTransition("deferred connectors remain to be configured")
    updated = dict(state.post_activation)
    updated[item] = "completed" if completed else "pending"
    return replace(state, post_activation=updated)


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
    flow = QUICK_START_STAGES if state.mode == "quick_start" else STAGES
    if completed_stage not in flow:
        raise InvalidTransition(f"unknown stage: {completed_stage}")
    if state.stage not in flow:
        raise InvalidTransition("onboarding stage does not match its selected path")
    current_index = flow.index(state.stage)
    requested_index = flow.index(completed_stage)
    if state.mode == "quick_start":
        _validate_quick_start_receipt(state, receipt)
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


def _validate_quick_start_receipt(
    state: OnboardingState,
    receipt: Mapping[str, object],
) -> None:
    """Require concrete evidence for every abbreviated onboarding step."""

    if state.stage == "privacy" and receipt.get("privacy_approved") is not True:
        raise InvalidTransition("quick start requires explicit privacy approval")
    if state.stage == "workspace":
        root = receipt.get("workspace_root")
        if not isinstance(root, str) or not root.strip():
            raise InvalidTransition("quick start requires an approved workspace")
    if state.stage == "resume":
        source_receipt = receipt.get("resume_receipt")
        if not isinstance(source_receipt, str) or not source_receipt.strip():
            raise InvalidTransition("quick start requires a preserved resume receipt")
    if state.stage == "focus":
        target_work = receipt.get("target_work")
        hard_constraints = receipt.get("hard_constraints")
        if (
            not isinstance(target_work, list)
            or not target_work
            or any(not isinstance(item, str) or not item.strip() for item in target_work)
            or not isinstance(hard_constraints, list)
            or any(
                not isinstance(item, str) or not item.strip()
                for item in hard_constraints
            )
        ):
            raise InvalidTransition(
                "quick start requires target work and an explicit hard-constraints list"
            )
    if state.stage == "profile" and (
        receipt.get("profile_approved") is not True
        or receipt.get("criteria_approved") is not True
        or not state.profile_hash
        or not state.criteria_hash
    ):
        raise InvalidTransition("quick start requires approved profile and criteria hashes")
    if state.stage == "packet_defaults" and (
        not isinstance(receipt.get("resume_pages"), int)
        or isinstance(receipt.get("resume_pages"), bool)
        or receipt.get("resume_pages", 0) < 1
        or not isinstance(receipt.get("cover_letter_enabled"), bool)
    ):
        raise InvalidTransition("quick start requires explicit packet defaults")
    if state.stage == "connectors" and set(state.connectors) != set(CONNECTORS):
        raise InvalidTransition("quick start requires a saved decision for every connector")
    if state.stage == "schedule":
        sources = receipt.get("enabled_sources")
        if (
            not isinstance(sources, list)
            or not any(source in PUBLIC_DISCOVERY_SOURCES for source in sources)
        ):
            raise InvalidTransition("quick start requires a usable public discovery lane")
    if state.stage == "readiness" and receipt.get("ready") is not True:
        raise InvalidTransition("quick start activation requires a passing readiness receipt")


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
            "mode": state.mode,
            "post_activation": dict(sorted(state.post_activation.items())),
        },
    )


def load_onboarding_state(path: Path) -> OnboardingState:
    raw = load_json(path)
    if raw.get("schema_version") != 1:
        raise ValueError("onboarding state schema version is invalid")
    stage = raw.get("stage")
    completed = raw.get("completed", ())
    raw_connectors = raw.get("connectors", {})
    raw_receipts = raw.get("receipts", {})
    mode = raw.get("mode", "full")
    raw_post_activation = raw.get("post_activation", {})
    flow = QUICK_START_STAGES if mode == "quick_start" else STAGES
    if (
        not isinstance(stage, str)
        or mode not in {"full", "quick_start"}
        or stage not in flow
        or not isinstance(completed, list)
        or any(not isinstance(item, str) or item not in flow for item in completed)
        or len(set(completed)) != len(completed)
        or not isinstance(raw_connectors, Mapping)
        or not isinstance(raw_receipts, Mapping)
        or not isinstance(raw_post_activation, Mapping)
        or tuple(completed) != flow[: flow.index(stage)]
    ):
        raise ValueError("onboarding state is invalid")
    if any(
        not isinstance(name, str)
        or not isinstance(value, Mapping)
        or not isinstance(value.get("decision"), str)
        or not isinstance(value.get("capabilities", ()), list)
        for name, value in raw_connectors.items()
    ):
        raise ValueError("onboarding state is invalid")
    connectors = {
        name: ConnectorStatus(
            decision=value["decision"],
            capabilities=tuple(value.get("capabilities", ())),
        )
        for name, value in raw_connectors.items()
    }
    if (
        any(name not in CONNECTORS for name in connectors)
        or any(status.decision not in _CONNECTOR_DECISIONS for status in connectors.values())
        or any(
            not isinstance(capability, str)
            for status in connectors.values()
            for capability in status.capabilities
        )
        or any(
            not isinstance(name, str) or not isinstance(receipt, Mapping)
            for name, receipt in raw_receipts.items()
        )
        or any(
            value is not None and not isinstance(value, str)
            for value in (raw.get("profile_hash"), raw.get("criteria_hash"))
        )
        or any(
            name not in _POST_ACTIVATION_ITEMS
            or status not in {"pending", "completed"}
            for name, status in raw_post_activation.items()
        )
        or (
            mode == "quick_start"
            and set(raw_post_activation) != _POST_ACTIVATION_ITEMS
        )
        or (mode == "full" and bool(raw_post_activation))
    ):
        raise ValueError("onboarding state is invalid")
    loaded = OnboardingState(
        stage=stage,
        completed=tuple(completed),
        connectors=connectors,
        receipts={
            name: dict(receipt)
            for name, receipt in raw_receipts.items()
        },
        profile_hash=raw.get("profile_hash"),
        criteria_hash=raw.get("criteria_hash"),
        mode=mode,
        post_activation=dict(raw_post_activation),
    )
    if mode == "quick_start":
        if stage != "active" and any(
            status == "completed" for status in loaded.post_activation.values()
        ):
            raise ValueError("onboarding state is invalid")
        if (
            loaded.post_activation.get("connector_configuration") == "completed"
            and any(
                status.decision == "deferred"
                for status in loaded.connectors.values()
            )
        ):
            raise ValueError("onboarding state is invalid")
        try:
            for completed_stage in loaded.completed:
                completed_receipt = loaded.receipts.get(completed_stage)
                if not isinstance(completed_receipt, Mapping):
                    raise InvalidTransition("quick-start receipt is missing")
                _validate_quick_start_receipt(
                    replace(loaded, stage=completed_stage),
                    completed_receipt,
                )
        except InvalidTransition as exc:
            raise ValueError("onboarding state is invalid") from exc
    return loaded
