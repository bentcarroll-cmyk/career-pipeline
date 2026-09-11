import tempfile
import unittest
from pathlib import Path

from career_pipeline.migrations import apply_migration, plan_migration
from career_pipeline.workspace import create_workspace


class PluginUpdateTests(unittest.TestCase):
    def test_migration_preserves_source_resume_and_application_history(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            resume = workspace.sources / "Resume_Original.txt"
            packet = workspace.applications / "JOB-1_Example_Role" / "v001" / "Resume.pdf"
            packet.parent.mkdir(parents=True)
            resume.write_bytes(b"Synthetic resume bytes")
            packet.write_bytes(b"%PDF-1.4\nsynthetic\n%%EOF\n")
            (workspace.state / "config.json").write_text(
                '{"schema_version": 0}\n',
                encoding="utf-8",
            )
            expected_resume = resume.read_bytes()
            expected_packet = packet.read_bytes()

            plan = plan_migration(workspace, 1)
            apply_migration(plan, plan.confirmation_token)

            self.assertEqual(resume.read_bytes(), expected_resume)
            self.assertEqual(packet.read_bytes(), expected_packet)


if __name__ == "__main__":
    unittest.main()
