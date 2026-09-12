"""Confirmed, backed-up migrations for user-owned Career Pipeline workspaces."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .atomic import atomic_write_json, load_json
from .contracts import WorkspacePaths
from .indexes import rebuild_indexes
from .job_store import workspace_lock


CURRENT_WORKSPACE_SCHEMA = 2
_BACKUP_COMPLETION_FILE = "backup-complete.json"
_BACKUP_FORMAT_VERSION = 1


class MigrationError(ValueError):
    pass


@dataclass(frozen=True)
class MigrationPlan:
    workspace: WorkspacePaths
    from_version: int
    target_version: int
    state_inventory: tuple[tuple[str, int, str], ...]
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
    state_inventory = _state_inventory(workspace.state)
    if state_inventory != _state_inventory(workspace.state):
        raise MigrationError("workspace state changed while planning migration")
    config_inventory = next(
        (entry for entry in state_inventory if entry[0] == "config.json"),
        None,
    )
    if config_inventory != (
        "config.json",
        len(raw_bytes),
        hashlib.sha256(raw_bytes).hexdigest(),
    ):
        raise MigrationError("workspace state changed while planning migration")
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
    token_payload = json.dumps(
        {
            "from_version": from_version,
            "state_inventory": state_inventory,
            "target_version": target_version,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    token = hashlib.sha256(token_payload).hexdigest()[:20]
    backup_dir = (
        workspace.state
        / "backups"
        / f"migration-v{from_version}-to-v{target_version}-{token}"
    )
    return MigrationPlan(
        workspace=workspace,
        from_version=from_version,
        target_version=target_version,
        state_inventory=state_inventory,
        changes=tuple(changes),
        confirmation_token=token,
        backup_dir=backup_dir,
        jobs_existed=workspace.jobs.is_dir(),
        indexes_existed=workspace.indexes.is_dir(),
        next_id_existed=(workspace.state / "next-job-id.json").is_file(),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _state_files(state: Path) -> dict[Path, Path]:
    files: dict[Path, Path] = {}
    for path in sorted(state.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(state)
        if relative.parts[0] == "backups" or path.name == ".workspace.lock":
            continue
        files[relative] = path
    return files


def _inventory(files: Mapping[Path, Path]) -> dict[str, dict[str, object]]:
    return {
        relative.as_posix(): {
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
        for relative, path in sorted(files.items())
    }


def _inventory_rows(
    inventory: Mapping[str, Mapping[str, object]],
) -> tuple[tuple[str, int, str], ...]:
    return tuple(
        (
            relative,
            int(metadata["size"]),
            str(metadata["sha256"]),
        )
        for relative, metadata in sorted(inventory.items())
    )


def _state_inventory(state: Path) -> tuple[tuple[str, int, str], ...]:
    return _inventory_rows(_inventory(_state_files(state)))


def _backup_files(backup_dir: Path) -> dict[Path, Path]:
    return {
        path.relative_to(backup_dir): path
        for path in sorted(backup_dir.rglob("*"))
        if path.is_file()
        and path.relative_to(backup_dir) != Path(_BACKUP_COMPLETION_FILE)
    }


def _verify_backup(
    backup_dir: Path,
    required_inventory: tuple[tuple[str, int, str], ...] | None = None,
) -> dict[Path, Path]:
    marker = backup_dir / _BACKUP_COMPLETION_FILE
    try:
        completion = load_json(marker)
        if completion.get("schema_version") != _BACKUP_FORMAT_VERSION:
            raise MigrationError("migration backup completion marker is invalid")
        expected = completion["files"]
        if not isinstance(expected, Mapping):
            raise MigrationError("migration backup completion marker is invalid")
        files = _backup_files(backup_dir)
        actual = _inventory(files)
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise MigrationError("migration backup is incomplete or invalid") from exc
    if actual != expected:
        raise MigrationError("migration backup inventory or hashes do not match")
    if required_inventory is not None and _inventory_rows(actual) != required_inventory:
        raise MigrationError("migration backup does not match the migration plan")
    return files


def _backup_state(plan: MigrationPlan) -> None:
    if _state_inventory(plan.workspace.state) != plan.state_inventory:
        raise MigrationError("migration plan is stale; create a new plan")
    if plan.backup_dir.exists():
        _verify_backup(plan.backup_dir, plan.state_inventory)
        return
    backup_parent = plan.backup_dir.parent
    backup_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{plan.backup_dir.name}.staging-",
            dir=str(backup_parent),
        )
    )
    try:
        sources = _state_files(plan.workspace.state)
        if Path(_BACKUP_COMPLETION_FILE) in sources:
            raise MigrationError("workspace state uses a reserved backup file name")
        expected = _inventory(sources)
        if _inventory_rows(expected) != plan.state_inventory:
            raise MigrationError("migration plan is stale; create a new plan")
        for relative, source in sorted(sources.items()):
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        if _inventory(_state_files(plan.workspace.state)) != expected:
            raise MigrationError("workspace state changed while creating its backup")
        if _inventory(_backup_files(staging)) != expected:
            raise MigrationError("migration backup verification failed")
        for path in _backup_files(staging).values():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
        atomic_write_json(
            staging / _BACKUP_COMPLETION_FILE,
            {
                "schema_version": _BACKUP_FORMAT_VERSION,
                "files": expected,
            },
        )
        _fsync_directory(staging)
        os.replace(staging, plan.backup_dir)
        _fsync_directory(backup_parent)
        _verify_backup(plan.backup_dir, plan.state_inventory)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


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
    backup_files = _verify_backup(plan.backup_dir, plan.state_inventory)
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


def _revalidate_plan(plan: MigrationPlan) -> None:
    current = plan_migration(plan.workspace, plan.target_version)
    if current != plan:
        raise MigrationError("migration plan is stale; create a new plan")


def apply_migration(
    plan: MigrationPlan,
    confirmation_token: str,
) -> MigrationPlan:
    if confirmation_token != plan.confirmation_token:
        raise MigrationError("migration confirmation token does not match the plan")
    backup_complete = False
    try:
        with workspace_lock(plan.workspace):
            _revalidate_plan(plan)
            _backup_state(plan)
            backup_complete = True
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
        if not backup_complete:
            if isinstance(exc, MigrationError):
                raise
            raise MigrationError(
                "migration failed before state mutation; original state is unchanged"
            ) from exc
        try:
            with workspace_lock(plan.workspace):
                _restore_state(plan)
                _remove_new_derived_paths(plan)
        except Exception as rollback_exc:
            raise MigrationError(
                f"migration failed and rollback also failed: {rollback_exc}"
            ) from exc
        raise MigrationError("migration failed; original state was restored") from exc
    return plan
