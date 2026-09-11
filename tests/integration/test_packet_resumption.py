import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch
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
from career_pipeline.job_store import create_job
from career_pipeline.workspace import create_workspace
from tests.unit.test_job_store import synthetic_assessment, synthetic_candidate
from tests.unit.test_packets import seed_job


class PacketResumptionTests(unittest.TestCase):
    def test_stale_caller_manifest_merges_with_existing_job_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            first_job = seed_job(workspace)
            second_job = create_job(
                workspace,
                replace(
                    synthetic_candidate(),
                    source_record_id="synthetic-record-2",
                    requisition_id="SYN-602",
                    title="Strategy Operations Lead",
                    raw_field_hash="b" * 64,
                ),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting two\n",
                assessment_markdown="# Synthetic assessment two\n",
                occurred_at="2026-09-11T20:01:00Z",
            )["job_id"]
            start_packet(
                workspace,
                first_job,
                PacketOptions(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )

            merged, _ = start_packet(
                workspace,
                second_job,
                PacketOptions(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:06:00Z",
                explicit_request=True,
            )

            self.assertEqual(set(merged.packets), {first_job, second_job})
            persisted = load_manifest(
                workspace.state / "application-manifest.json"
            )
            self.assertEqual(set(persisted.packets), {first_job, second_job})

    def test_directory_creation_failure_keeps_recoverable_version_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            with patch(
                "career_pipeline.packets._ensure_packet_directories",
                side_effect=OSError("synthetic interruption"),
            ):
                with self.assertRaises(OSError):
                    tape = ApplicationManifest()
                    start_packet(
                        workspace,
                        job_id,
                        PacketOptions(),
                        tape,
                        occurred_at="2026-09-11T20:05:00Z",
                        explicit_request=True,
                    )

            recovered, record = start_packet(
                workspace,
                job_id,
                PacketOptions(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:06:00Z",
                explicit_request=True,
            )

            self.assertEqual(record.version, "v001")
            self.assertEqual(recovered.packets[job_id][-1].version, "v001")
            self.assertTrue((workspace.root / record.working_dir).is_dir())

    def test_retry_after_lost_return_reuses_persisted_version_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)

            _, first = start_packet(
                workspace,
                job_id,
                PacketOptions(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            recovered, second = start_packet(
                workspace,
                job_id,
                PacketOptions(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:06:00Z",
                explicit_request=True,
            )

            self.assertEqual(first.version, "v001")
            self.assertEqual(second.version, "v001")
            self.assertEqual(recovered.packets[job_id][-1], first)
            self.assertTrue(
                (workspace.state / "application-manifest.json").is_file()
            )

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
