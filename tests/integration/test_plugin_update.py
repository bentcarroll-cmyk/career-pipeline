import json
import tempfile
import unittest
from pathlib import Path

from career_pipeline.migrations import apply_migration, plan_migration
from career_pipeline.workspace import create_workspace
from tests.unit.test_packets import seed_job


class PluginUpdateTests(unittest.TestCase):
    def test_migration_preserves_resume_jobs_events_and_application_history(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            resume = workspace.sources / "Resume_Original.txt"
            resume.write_bytes(b"Synthetic resume bytes")
            job_id = seed_job(workspace)
            packet = (
                workspace.applications
                / f"{job_id}_Example_Organization_Operations_Lead"
                / "v001"
                / "Resume.pdf"
            )
            packet.parent.mkdir(parents=True)
            packet.write_bytes(b"%PDF-1.4\nsynthetic\n%%EOF\n")
            config = workspace.state / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "timezone": "America/New_York",
                        "linear": {
                            "workspace_id": "synthetic-workspace",
                            "team_id": "synthetic-team",
                            "project_id": "synthetic-project",
                        },
                    }
                ),
                encoding="utf-8",
            )
            expected_resume = resume.read_bytes()
            expected_packet = packet.read_bytes()
            expected_job = (workspace.jobs / job_id / "job.json").read_bytes()
            expected_events = (workspace.jobs / job_id / "events.jsonl").read_bytes()

            plan = plan_migration(workspace, 2)
            apply_migration(plan, plan.confirmation_token)

            self.assertEqual(resume.read_bytes(), expected_resume)
            self.assertEqual(packet.read_bytes(), expected_packet)
            self.assertEqual((workspace.jobs / job_id / "job.json").read_bytes(), expected_job)
            self.assertEqual(
                (workspace.jobs / job_id / "events.jsonl").read_bytes(),
                expected_events,
            )
            self.assertTrue((workspace.indexes / "backlog.json").is_file())


if __name__ == "__main__":
    unittest.main()
