import tempfile
import unittest
from pathlib import Path

from career_pipeline.packets import (
    ApplicationManifest,
    PacketOptions,
    resume_action,
    start_packet,
)
from career_pipeline.workspace import create_workspace
from tests.unit.test_packets import seed_job


class PrepareApplicationIntegrationTests(unittest.TestCase):
    def test_changed_profile_requires_new_version_decision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            _, record = start_packet(
                workspace,
                job_id,
                PacketOptions(
                    cover_letter_enabled=False,
                    profile_hash="old-profile-hash",
                ),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            self.assertEqual(resume_action(record, "new-profile-hash"), "restart_required")
            self.assertEqual(resume_action(record, "old-profile-hash"), "resume")


if __name__ == "__main__":
    unittest.main()
