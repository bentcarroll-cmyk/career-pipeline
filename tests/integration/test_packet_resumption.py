import tempfile
import unittest
from pathlib import Path

from career_pipeline.packets import (
    ApplicationManifest,
    PacketOptions,
    advance_packet,
    load_manifest,
    resume_queue,
    save_manifest,
    start_packet,
)
from career_pipeline.workspace import create_workspace
from tests.unit.test_packets import seed_job


class PacketResumptionTests(unittest.TestCase):
    def test_interrupted_packet_round_trips_and_resumes_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            manifest, _ = start_packet(
                workspace,
                job_id,
                PacketOptions(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            manifest = advance_packet(
                manifest,
                job_id,
                "posting_verified",
                {
                    "posting_url": "https://jobs.example/postings/SYN-601",
                    "application_url": "https://jobs.example/apply/SYN-601",
                },
            )
            path = workspace.state / "application-manifest.json"
            save_manifest(path, manifest)
            loaded = load_manifest(path)
            self.assertEqual(loaded, manifest)
            self.assertEqual([record.job_id for record in resume_queue(loaded)], [job_id])

            unchanged, record = start_packet(
                workspace,
                job_id,
                PacketOptions(),
                loaded,
                occurred_at="2026-09-11T20:10:00Z",
                explicit_request=True,
            )
            self.assertEqual(unchanged, loaded)
            self.assertEqual(record.version, "v001")


if __name__ == "__main__":
    unittest.main()
