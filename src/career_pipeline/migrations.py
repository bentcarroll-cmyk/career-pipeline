"""Confirmed, backed-up migrations for user-owned Career Pipeline workspaces."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .atomic import atomic_write_json, load_json
from .contracts import WorkspacePaths
from .indexes import rebuild_indexes
from .job_store import workspace_lock


CURRENT_WORKSPACE_SCHEMA = 2


class MigrationError(ValueError):
    pass


@dataclass(frozen=True)
class MigrationPlan:
    workspace: WorkspacePaths
    from_version: int
    target_version: int
    changes: tuple[str, ...]
    confirmation_token: str
    backup_dir: Path
    jobs_existed: bool
    indexes_existed: bool
    next_id_existed: bool


def plan_migration(
    workspace: WorkspacePaths,
    target_version: int = CURRENT_WORKSPACE_SCHEMA,
) -> MigrationPlan:
    if target_version != CURRENT_WORKSPACE_SCHEMA:
        raise MigrationError("unsupported migration target")
    config_path = workspace.state / "config.json"
    try:
        raw_bytes = config_path.read_bytes()
        config = json.loads(raw_bytes)
        from_version = config["schema_version"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise MigrationError("workspace configuration is unreadable") from exc
    if not isinstance(from_version, int) or isinstance(from_version, bool):
        raise MigrationError("workspace schema version is invalid")
    if from_version > target_version:
        raise MigrationError("workspace uses an unknown future schema version")
    if from_version < 0:
        raise MigrationError("workspace schema version is invalid")
    changes: list[str] = []
    if from_version < target_version:
        changes.append(f"upgrade_config_to_{target_version}")
    if not workspace.jobs.is_dir():
        changes.append("create_jobs_directory")
    if not workspace.indexes.is_dir():
        changes.append("create_indexes_directory")
    if not (workspace.state / "next-job-id.json").is_file():
        changes.append("initialize_next_job_id")
    changes.append("rebuild_indexes")
    token = hashlib.sha256(
        raw_bytes + f"\x00{from_version}\x00{target_version}".encode("ascii")
    ).hexdigest()[:20]
    backup_dir = (
        workspace.state
        / "backups"
        / f"migration-v{from_version}-to-v{target_version}-{token}"
    )
    return MigrationPlan(
        workspace=workspace,
        from_version=from_version,
        target_version=target_version,
        changes=tuple(changes),
        confirmation_token=token,
        backup_dir=backup_dir,
        jobs_existed=workspace.jobs.is_dir(),
        indexes_existed=workspace.indexes.is_dir(),
        next_id_existed=(workspace.state / "next-job-id.json").is_file(),
    )


def _backup_state(plan: MigrationPlan) -> None:
    if plan.backup_dir.exists():
        if not (plan.backup_dir / "config.json").is_file():
            raise MigrationError("existing migration backup is incomplete")
        return
    plan.backup_dir.mkdir(parents=True)
    for source in sorted(plan.workspace.state.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(plan.workspace.state)
        if relative.parts[0] == "backups" or source.name == ".workspace.lock":
            continue
        destination = plan.backup_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _migrated_config(
    current: Mapping[str, object],
    workspace: WorkspacePaths,
) -> dict[str, object]:
    migrated = dict(current)
    migrated["schema_version"] = CURRENT_WORKSPACE_SCHEMA
    migrated["workspace_root"] = str(workspace.root)
    migrated["paths"] = {
        "profile": "Profile",
        "sources": "Sources",
        "jobs": "Jobs",
        "applications": "Applications",
        "indexes": "Indexes",
        "runs": "Runs",
        "state": "State",
    }
    migrated.setdefault("profile_approved", False)
    migrated.setdefault("criteria_approved", False)
    migrated.setdefault(
        "packet_defaults",
        {
            "resume_pages": 2,
            "cover_letter_enabled": True,
            "cover_letter_pages": 1,
        },
    )
    connectors_raw = migrated.get("connectors", {})
    connectors = dict(connectors_raw) if isinstance(connectors_raw, Mapping) else {}
    linear_settings = migrated.pop("linear", None)
    if isinstance(linear_settings, Mapping):
        existing_raw = connectors.get("linear", {})
        existing = dict(existing_raw) if isinstance(existing_raw, Mapping) else {}
        existing.setdefault("decision", "unavailable")
        existing.setdefault("capabilities", [])
        existing["settings"] = dict(linear_settings)
        connectors["linear"] = existing
    migrated["connectors"] = connectors
    return migrated


def _restore_state(plan: MigrationPlan) -> None:
    state = plan.workspace.state
    backup_files = {
        path.relative_to(plan.backup_dir): path
        for path in plan.backup_dir.rglob("*")
        if path.is_file()
    }
    current_files = [
        path
        for path in state.rglob("*")
        if path.is_file()
        and path.name != ".workspace.lock"
        and path.relative_to(state).parts[0] != "backups"
    ]
    for path in current_files:
        relative = path.relative_to(state)
        if relative not in backup_files:
            path.unlink()
    for relative, source in backup_files.items():
        destination = state / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _remove_new_derived_paths(plan: MigrationPlan) -> None:
    if not plan.indexes_existed and plan.workspace.indexes.exists():
        for name in ("backlog.json", "deduplication.json"):
            (plan.workspace.indexes / name).unlink(missing_ok=True)
        try:
            plan.workspace.indexes.rmdir()
        except OSError:
            pass
    if not plan.jobs_existed and plan.workspace.jobs.exists():
        try:
            plan.workspace.jobs.rmdir()
        except OSError:
            pass


def apply_migration(
    plan: MigrationPlan,
    confirmation_token: str,
) -> MigrationPlan:
    if confirmation_token != plan.confirmation_token:
        raise MigrationError("migration confirmation token does not match the plan")
    try:
        with workspace_lock(plan.workspace):
            _backup_state(plan)
            plan.workspace.jobs.mkdir(parents=True, exist_ok=True)
            plan.workspace.indexes.mkdir(parents=True, exist_ok=True)
            next_id = plan.workspace.state / "next-job-id.json"
            if not next_id.exists():
                atomic_write_json(next_id, {"schema_version": 1, "next_id": 1})
            config_path = plan.workspace.state / "config.json"
            current = load_json(config_path)
            atomic_write_json(config_path, _migrated_config(current, plan.workspace))
        rebuild_indexes(plan.workspace)
    except Exception as exc:
        try:
            with workspace_lock(plan.workspace):
                if plan.backup_dir.exists():
                    _restore_state(plan)
            _remove_new_derived_paths(plan)
        except Exception as rollback_exc:
            raise MigrationError(
                f"migration failed and rollback also failed: {rollback_exc}"
            ) from exc
        raise MigrationError("migration failed; original state was restored") from exc
    return plan
