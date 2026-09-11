import json
import tempfile
import unittest
from pathlib import Path

from career_pipeline.migrations import (
    MigrationError,
    apply_migration,
    plan_migration,
)
from career_pipeline.workspace import create_workspace


class MigrationTests(unittest.TestCase):
    def test_plan_is_dry_run_and_apply_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            config = workspace.state / "config.json"
            config.write_text(
                json.dumps({"schema_version": 0, "timezone": "America/New_York"}),
                encoding="utf-8",
            )
            plan = plan_migration(workspace, 1)
            self.assertFalse(plan.backup_dir.exists())
            with self.assertRaises(MigrationError):
                apply_migration(plan, "wrong-token")
            receipt = apply_migration(plan, plan.confirmation_token)
            self.assertTrue(receipt.backup_dir.is_dir())
            self.assertEqual(json.loads(config.read_text())["schema_version"], 1)

    def test_interrupted_migration_restores_original_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            first = workspace.state / "config.json"
            second = workspace.state / "onboarding-state.json"
            first.write_text('{"schema_version": 0, "value": "first"}\n', encoding="utf-8")
            second.write_text('{"schema_version": 0, "value": "second"}\n', encoding="utf-8")
            before = {path.name: path.read_bytes() for path in (first, second)}
            plan = plan_migration(workspace, 1)
            with self.assertRaises(MigrationError):
                apply_migration(plan, plan.confirmation_token, fail_after=1)
            self.assertEqual(
                {path.name: path.read_bytes() for path in (first, second)},
                before,
            )

    def test_unknown_future_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            (workspace.state / "config.json").write_text(
                '{"schema_version": 9}\n',
                encoding="utf-8",
            )
            with self.assertRaises(MigrationError):
                plan_migration(workspace, 1)


if __name__ == "__main__":
    unittest.main()
