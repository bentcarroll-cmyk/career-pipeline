"""Activation readiness checks with stable remediation codes."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .atomic import atomic_write_json, load_json
from .capabilities import CONNECTORS, DISCOVERY_ACTIONS, PUBLIC_DISCOVERY_SOURCES
from .contracts import WorkspacePaths
from .indexes import load_indexes
from .job_store import workspace_lock
from .onboarding import OnboardingState, load_onboarding_state
from .workspace import WorkspaceError, load_source_resume_receipt


_CONFIG_PATHS = {
    "profile": "Profile",
    "sources": "Sources",
    "jobs": "Jobs",
    "applications": "Applications",
    "indexes": "Indexes",
    "runs": "Runs",
    "state": "State",
}
_PROFILE_EVIDENCE_ID = re.compile(r"\bEV-[A-Za-z0-9][A-Za-z0-9_-]*\b")


@dataclass(frozen=True)
class ReadinessReport:
    failure_codes: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.failure_codes


def _persisted_config_is_valid(config: Mapping[str, object], root: Path) -> bool:
    workspace_root = config.get("workspace_root")
    paths = config.get("paths")
    return (
        config.get("schema_version") == 2
        and isinstance(workspace_root, str)
        and Path(workspace_root).resolve() == root.resolve()
        and isinstance(config.get("timezone"), str)
        and bool(config.get("timezone"))
        and isinstance(paths, Mapping)
        and all(paths.get(name) == relative for name, relative in _CONFIG_PATHS.items())
        and config.get("profile_approved") is True
        and config.get("criteria_approved") is True
        and isinstance(config.get("connectors"), Mapping)
    )


def check_readiness(
    config: Mapping[str, object],
    onboarding: OnboardingState,
) -> ReadinessReport:
    failures: list[str] = []
    root_value = config.get("workspace_root")
    persisted_config: Mapping[str, object] | None = None
    persisted_onboarding: OnboardingState | None = None
    if not isinstance(root_value, str) or not Path(root_value).is_dir():
        failures.append("workspace_unavailable")
    else:
        root = Path(root_value).resolve()
        try:
            persisted_config = load_json(root / "State" / "config.json")
        except (OSError, ValueError):
            failures.append("persisted_config_invalid")
        try:
            persisted_onboarding = load_onboarding_state(root / "State" / "onboarding-state.json")
        except (OSError, ValueError, KeyError, TypeError):
            failures.append("persisted_onboarding_invalid")
        if persisted_config is not None:
            if not _persisted_config_is_valid(persisted_config, root):
                failures.append("persisted_config_invalid")
            if persisted_config != config:
                failures.append("persisted_config_mismatch")
            config = persisted_config
        if persisted_onboarding is not None:
            if persisted_onboarding != onboarding:
                failures.append("persisted_onboarding_mismatch")
            onboarding = persisted_onboarding
        for relative in (
            "Profile",
            "Sources",
            "Jobs",
            "Applications",
            "Indexes",
            "Runs",
            "State",
        ):
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
            profile_bytes = profile.read_bytes()
            profile_hash = hashlib.sha256(profile_bytes).hexdigest()
            criteria_hash = hashlib.sha256(criteria.read_bytes()).hexdigest()
            if (
                onboarding.profile_hash != profile_hash
                or onboarding.criteria_hash != criteria_hash
            ):
                failures.append("approved_files_changed")
            if _PROFILE_EVIDENCE_ID.search(
                profile_bytes.decode("utf-8", errors="replace")
            ) is None:
                failures.append("profile_evidence_missing")
        receipt_workspace = WorkspacePaths(
            root=root.resolve(),
            profile=(root / "Profile").resolve(),
            sources=(root / "Sources").resolve(),
            jobs=(root / "Jobs").resolve(),
            applications=(root / "Applications").resolve(),
            indexes=(root / "Indexes").resolve(),
            runs=(root / "Runs").resolve(),
            state=(root / "State").resolve(),
        )
        receipt_path = receipt_workspace.state / "source-resume-receipt.json"
        if not receipt_path.is_file():
            failures.append("resume_receipt_missing")
        else:
            try:
                receipt = load_source_resume_receipt(receipt_workspace)
                if len(resumes) != 1 or receipt.destination != resumes[0]:
                    failures.append("resume_receipt_destination_mismatch")
                else:
                    resume_stat = receipt.destination.lstat()
                    if receipt.destination.is_symlink() or not stat.S_ISREG(resume_stat.st_mode):
                        failures.append("resume_not_regular_file")
                    elif resume_stat.st_size != receipt.size:
                        failures.append("resume_size_mismatch")
                    elif hashlib.sha256(receipt.destination.read_bytes()).hexdigest() != receipt.sha256:
                        failures.append("resume_hash_mismatch")
            except (OSError, ValueError, WorkspaceError):
                failures.append("resume_receipt_invalid")
        workspace = WorkspacePaths(
            root=root.resolve(),
            profile=(root / "Profile").resolve(),
            sources=(root / "Sources").resolve(),
            jobs=(root / "Jobs").resolve(),
            applications=(root / "Applications").resolve(),
            indexes=(root / "Indexes").resolve(),
            runs=(root / "Runs").resolve(),
            state=(root / "State").resolve(),
        )
        probe = workspace.state / ".readiness-probe.json"
        try:
            counter = load_json(workspace.state / "next-job-id.json")
            next_id = counter.get("next_id")
            if (
                counter.get("schema_version") != 1
                or not isinstance(next_id, int)
                or isinstance(next_id, bool)
                or not 1 <= next_id <= 1000000
            ):
                raise ValueError("invalid next job ID state")
            with workspace_lock(workspace):
                atomic_write_json(probe, {"schema_version": 1, "ready": True})
                if load_json(probe).get("ready") is not True:
                    raise ValueError("readiness probe mismatch")
                probe.unlink()
            load_indexes(workspace)
        except (OSError, ValueError):
            failures.append("local_store_invalid")
        finally:
            probe.unlink(missing_ok=True)

    timezone = config.get("timezone")
    try:
        if not isinstance(timezone, str) or not timezone:
            raise ZoneInfoNotFoundError
        ZoneInfo(timezone)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        failures.append("timezone_invalid")

    schedule = config.get("discovery_schedule")
    if not isinstance(schedule, Mapping):
        failures.append("discovery_schedule_invalid")
    else:
        weekdays = schedule.get("weekdays")
        runs_per_day = schedule.get("runs_per_day")
        if (
            schedule.get("frequency") not in {"weekday", "daily", "weekly", "custom"}
            or not isinstance(weekdays, list)
            or not weekdays
            or any(
                not isinstance(day, str)
                or day not in {"MO", "TU", "WE", "TH", "FR", "SA", "SU"}
                for day in weekdays
            )
            or len(set(weekdays)) != len(weekdays)
            or not isinstance(runs_per_day, int)
            or isinstance(runs_per_day, bool)
            or not 1 <= runs_per_day <= 24
        ):
            failures.append("discovery_schedule_invalid")
        if schedule.get("timezone") != timezone:
            failures.append("discovery_schedule_timezone_mismatch")

    if not onboarding.profile_hash or not onboarding.criteria_hash:
        failures.append("profile_not_approved")
    if onboarding.stage not in {"readiness", "active"}:
        failures.append("onboarding_not_ready")
    if any(name not in onboarding.connectors for name in CONNECTORS):
        failures.append("connector_decisions_incomplete")
    sources = config.get("enabled_sources")
    if onboarding.mode == "quick_start":
        schedule_receipt = onboarding.receipts.get("schedule", {})
        receipt_sources = (
            schedule_receipt.get("enabled_sources")
            if isinstance(schedule_receipt, Mapping)
            else None
        )
        actual_source_set = (
            frozenset(sources)
            if isinstance(sources, list)
            and all(isinstance(source, str) for source in sources)
            else frozenset()
        )
        receipt_source_set = (
            frozenset(receipt_sources)
            if isinstance(receipt_sources, list)
            and all(isinstance(source, str) for source in receipt_sources)
            else frozenset()
        )
        if not actual_source_set.intersection(PUBLIC_DISCOVERY_SOURCES):
            failures.append("quick_start_public_discovery_source_missing")
        if actual_source_set != receipt_source_set:
            failures.append("quick_start_discovery_lane_mismatch")
    if not isinstance(sources, list) or not any(
        isinstance(source, str)
        and (
            source in PUBLIC_DISCOVERY_SOURCES
            or (
                source in onboarding.connectors
                and onboarding.connectors[source].decision == "connected"
                and bool(
                    set(onboarding.connectors[source].capabilities).intersection(
                        DISCOVERY_ACTIONS.get(source, frozenset())
                    )
                )
            )
        )
        for source in sources
    ):
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
