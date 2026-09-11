import tempfile
import unittest
from pathlib import Path

from career_pipeline.packets import (
    ApplicationManifest,
    PacketOptions,
    PacketTicket,
    advance_packet,
    load_manifest,
    resume_queue,
    save_manifest,
    start_packet,
)
from career_pipeline.workspace import create_workspace


class PacketResumptionTests(unittest.TestCase):
    def test_interrupted_packet_round_trips_and_resumes_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            manifest, _ = start_packet(
                PacketTicket("JOB-9", "Example Org", "Role", "posting", "apply"),
                workspace,
                PacketOptions(),
                ApplicationManifest(),
            )
            manifest = advance_packet(
                manifest,
                "JOB-9",
                "posting_verified",
                {"posting_url": "posting", "application_url": "apply"},
            )
            path = workspace.state / "application-manifest.json"
            save_manifest(path, manifest)
            loaded = load_manifest(path)
            self.assertEqual(loaded, manifest)
            self.assertEqual([record.ticket_id for record in resume_queue(loaded)], ["JOB-9"])

            unchanged, record = start_packet(
                PacketTicket("JOB-9", "Example Org", "Role", "posting", "apply"),
                workspace,
                PacketOptions(),
                loaded,
            )
            self.assertEqual(unchanged, loaded)
            self.assertEqual(record.version, "v001")


if __name__ == "__main__":
    unittest.main()
