import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from career_pipeline.contracts import WorkspacePaths
from career_pipeline.migrations import (
    MigrationError,
    apply_migration,
    plan_migration,
)
from career_pipeline.workspace import create_workspace, workspace_paths


def prototype_config() -> dict[str, object]:
    return {
        "schema_version": 1,
        "workspace_root": "/approved-at-runtime",
        "timezone": "America/New_York",
        "paths": {
            "profile": "Profile",
            "sources": "Sources",
            "applications": "Applications",
            "runs": "Runs",
            "state": "State",
        },
        "linear": {
            "workspace_id": "synthetic-workspace",
            "team_id": "synthetic-team",
            "project_id": "synthetic-project",
        },
        "profile_approved": False,
        "criteria_approved": False,
        "connectors": {"linear": {"decision": "connected"}},
        "packet_defaults": {
            "resume_pages": 2,
            "cover_letter_enabled": True,
            "cover_letter_pages": 1,
        },
    }


def seed_migration_state(workspace: WorkspacePaths) -> dict[Path, bytes]:
    state = workspace.state
    seeded = {
        Path("config.json"): json.dumps(prototype_config(), indent=2).encode("utf-8"),
        Path("discovery-state.json"): b'{"cursor":"synthetic-discovery"}\n',
        Path("next-job-id.json"): b'{"schema_version":1,"next_id":42}\n',
        Path("onboarding-state.json"): b'{"stage":"synthetic-onboarding"}\n',
    }
    for relative, payload in seeded.items():
        (state / relative).write_bytes(payload)
    return seeded


def migration_state_bytes(workspace: WorkspacePaths) -> dict[Path, bytes]:
    state = workspace.state
    return {
        path.relative_to(state): path.read_bytes()
        for path in state.rglob("*")
        if path.is_file()
        and path.name != ".workspace.lock"
        and path.relative_to(state).parts[0] != "backups"
    }


class MigrationTests(unittest.TestCase):
    def test_path_resolution_for_a_dry_run_does_not_create_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "Synthetic-Career"

            paths = workspace_paths(root)

            self.assertEqual(paths.root, root.resolve())
            self.assertFalse(root.exists())

    def test_plan_is_dry_run_and_apply_requires_confirmation_and_backup(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            config = workspace.state / "config.json"
            original = json.dumps(prototype_config(), sort_keys=True).encode("utf-8")
            config.write_bytes(original)

            plan = plan_migration(workspace, 2)

            self.assertFalse(plan.backup_dir.exists())
            self.assertIn("upgrade_config_to_2", plan.changes)
            with self.assertRaises(MigrationError):
                apply_migration(plan, "wrong-confirmation")
            apply_migration(plan, plan.confirmation_token)

            migrated = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(migrated["schema_version"], 2)
            self.assertEqual(migrated["paths"]["jobs"], "Jobs")
            self.assertEqual(migrated["paths"]["indexes"], "Indexes")
            self.assertNotIn("linear", migrated)
            self.assertEqual(
                migrated["connectors"]["linear"]["settings"]["team_id"],
                "synthetic-team",
            )
            self.assertEqual(
                (plan.backup_dir / "config.json").read_bytes(),
                original,
            )
            completion = json.loads(
                (plan.backup_dir / "backup-complete.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                completion["files"]["config.json"]["sha256"],
                hashlib.sha256(original).hexdigest(),
            )

    def _assert_backup_copy_failure_preserves_original_state(
        self,
        copy_number: int,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            expected = seed_migration_state(workspace)
            plan = plan_migration(workspace, 2)
            real_copy2 = shutil.copy2
            copy_calls = 0

            def fail_selected_copy(
                source: Path,
                destination: Path,
                *args: object,
                **kwargs: object,
            ) -> Path:
                nonlocal copy_calls
                copy_calls += 1
                if copy_calls == copy_number:
                    raise OSError("synthetic backup interruption")
                return real_copy2(source, destination, *args, **kwargs)

            with patch(
                "career_pipeline.migrations.shutil.copy2",
                side_effect=fail_selected_copy,
            ):
                with self.assertRaises(MigrationError):
                    apply_migration(plan, plan.confirmation_token)

            self.assertEqual(migration_state_bytes(workspace), expected)
            self.assertFalse(plan.backup_dir.exists())

    def test_first_backup_copy_failure_preserves_every_original_byte(self) -> None:
        self._assert_backup_copy_failure_preserves_original_state(1)

    def test_middle_backup_copy_failure_preserves_every_original_byte(self) -> None:
        self._assert_backup_copy_failure_preserves_original_state(2)

    def test_final_backup_copy_failure_preserves_every_original_byte(self) -> None:
        self._assert_backup_copy_failure_preserves_original_state(4)

    def test_stale_plan_is_rejected_under_lock_before_state_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            seed_migration_state(workspace)
            plan = plan_migration(workspace, 2)
            changed = json.dumps(
                {**prototype_config(), "timezone": "America/Chicago"},
                indent=2,
            ).encode("utf-8")
            (workspace.state / "config.json").write_bytes(changed)
            expected = migration_state_bytes(workspace)

            with self.assertRaisesRegex(MigrationError, "stale"):
                apply_migration(plan, plan.confirmation_token)

            self.assertEqual(migration_state_bytes(workspace), expected)
            self.assertFalse(plan.backup_dir.exists())

    def test_retry_rejects_non_config_state_changed_after_backup(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            seed_migration_state(workspace)
            plan = plan_migration(workspace, 2)

            with patch(
                "career_pipeline.migrations.rebuild_indexes",
                side_effect=OSError("synthetic first-attempt interruption"),
            ):
                with self.assertRaises(MigrationError):
                    apply_migration(plan, plan.confirmation_token)

            self.assertTrue(plan.backup_dir.is_dir())
            changed_discovery = b'{"cursor":"newer-synthetic-discovery"}\n'
            (workspace.state / "discovery-state.json").write_bytes(changed_discovery)
            expected = migration_state_bytes(workspace)

            with patch(
                "career_pipeline.migrations.rebuild_indexes",
                side_effect=OSError("synthetic retry interruption"),
            ):
                with self.assertRaises(MigrationError) as caught:
                    apply_migration(plan, plan.confirmation_token)

            self.assertEqual(migration_state_bytes(workspace), expected)
            self.assertEqual(
                (workspace.state / "discovery-state.json").read_bytes(),
                changed_discovery,
            )
            self.assertIn("stale", str(caught.exception))

    def test_corrupt_backup_is_not_used_for_restore(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            expected = seed_migration_state(workspace)
            plan = plan_migration(workspace, 2)

            with patch(
                "career_pipeline.migrations.rebuild_indexes",
                side_effect=OSError("synthetic interruption"),
            ):
                with self.assertRaises(MigrationError):
                    apply_migration(plan, plan.confirmation_token)

            self.assertEqual(migration_state_bytes(workspace), expected)
            (plan.backup_dir / "config.json").write_bytes(b"corrupt backup bytes")

            with self.assertRaises(MigrationError):
                apply_migration(plan, plan.confirmation_token)

            self.assertEqual(migration_state_bytes(workspace), expected)

    def test_failure_rolls_back_original_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            config = workspace.state / "config.json"
            original = json.dumps(prototype_config(), indent=2).encode("utf-8")
            config.write_bytes(original)
            plan = plan_migration(workspace, 2)

            with patch(
                "career_pipeline.migrations.rebuild_indexes",
                side_effect=OSError("synthetic interruption"),
            ):
                with self.assertRaises(MigrationError):
                    apply_migration(plan, plan.confirmation_token)

            self.assertEqual(config.read_bytes(), original)
            self.assertTrue((plan.backup_dir / "config.json").is_file())

    def test_unknown_future_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            (workspace.state / "config.json").write_text(
                '{"schema_version": 9}\n',
                encoding="utf-8",
            )
            with self.assertRaises(MigrationError):
                plan_migration(workspace, 2)


if __name__ == "__main__":
    unittest.main()
