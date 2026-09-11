import tempfile
import unittest
from pathlib import Path

from career_pipeline.packets import (
    ApplicationManifest,
    PacketOptions,
    PacketTicket,
    resume_action,
    start_packet,
)
from career_pipeline.workspace import create_workspace


class PrepareApplicationIntegrationTests(unittest.TestCase):
    def test_changed_profile_requires_new_version_decision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            _, record = start_packet(
                PacketTicket("JOB-20", "Example Org", "Role", "posting", "apply"),
                workspace,
                PacketOptions(
                    cover_letter_enabled=False,
                    profile_hash="old-profile-hash",
                ),
                ApplicationManifest(),
            )
            self.assertEqual(
                resume_action(record, "new-profile-hash"),
                "restart_required",
            )
            self.assertEqual(
                resume_action(record, "old-profile-hash"),
                "resume",
            )


if __name__ == "__main__":
    unittest.main()
