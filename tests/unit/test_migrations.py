import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
