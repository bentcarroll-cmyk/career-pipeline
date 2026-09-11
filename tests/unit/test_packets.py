import tempfile
import unittest
from pathlib import Path

from career_pipeline.job_store import create_job, read_job, update_job_status
from career_pipeline.packets import (
    ApplicationManifest,
    InvalidPacketTransition,
    PacketOptions,
    advance_packet,
    complete_local_delivery,
    load_manifest,
    start_packet,
    verify_local_artifacts,
)
from career_pipeline.quality import QualityReceipt
from career_pipeline.workspace import create_workspace
from tests.unit.test_job_store import synthetic_assessment, synthetic_candidate


def seed_job(workspace) -> str:
    return str(
        create_job(
            workspace,
            synthetic_candidate(),
            synthetic_assessment(),
            posting_markdown="# Synthetic posting\n",
            assessment_markdown="# Synthetic assessment\n",
            occurred_at="2026-09-11T20:00:00Z",
        )["job_id"]
    )


def advance_to_saved(manifest, job_id, artifact_hashes):
    for stage, receipt in (
        (
            "posting_verified",
            {
                "posting_url": "https://jobs.example/postings/SYN-601",
                "application_url": "https://jobs.example/apply/SYN-601",
            },
        ),
        ("drafted", {"draft_hashes": {"resume": "a" * 64}}),
        ("quality_checked", QualityReceipt.all_passed(2, None).as_dict()),
        ("saved", {"artifact_hashes": artifact_hashes}),
    ):
        manifest = advance_packet(manifest, job_id, stage, receipt)
    return manifest


class PacketTests(unittest.TestCase):
    def test_packet_work_preserves_advanced_lifecycle_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            update_job_status(
                workspace,
                job_id,
                "offer",
                occurred_at="2026-09-11T20:02:00Z",
            )

            manifest, record = start_packet(
                workspace,
                job_id,
                PacketOptions(cover_letter_enabled=False),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            actual_resume = workspace.root / record.resume_pdf
            actual_resume.write_bytes(b"%PDF-1.4\nsynthetic\n%%EOF\n")
            verification = verify_local_artifacts(workspace, record)
            manifest = advance_to_saved(manifest, job_id, verification.hashes)
            complete_local_delivery(
                workspace,
                manifest,
                job_id,
                occurred_at="2026-09-11T20:10:00Z",
            )

            canonical = read_job(workspace, job_id)
            self.assertEqual(canonical["status"], "offer")
            self.assertEqual(canonical["application_versions"][0]["version"], "v001")

    def test_final_paths_are_relative_and_directly_browseable_in_v001(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            manifest, record = start_packet(
                workspace,
                job_id,
                PacketOptions(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )

            self.assertEqual(record.version, "v001")
            self.assertFalse(record.version_dir.is_absolute())
            self.assertEqual(record.resume_pdf.parent, record.version_dir)
            self.assertEqual(record.cover_letter_pdf.parent, record.version_dir)
            self.assertEqual(record.working_dir.parent, record.version_dir)
            self.assertTrue((workspace.root / record.working_dir).is_dir())
            self.assertIn(job_id, manifest.packets)
            self.assertEqual(read_job(workspace, job_id)["status"], "prepare_application")

    def test_start_requires_a_current_explicit_request_and_existing_job(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            with self.assertRaises(InvalidPacketTransition):
                start_packet(
                    workspace,
                    job_id,
                    PacketOptions(),
                    ApplicationManifest(),
                    occurred_at="2026-09-11T20:05:00Z",
                    explicit_request=False,
                )
            with self.assertRaises(InvalidPacketTransition):
                start_packet(
                    workspace,
                    "JOB-999999",
                    PacketOptions(),
                    ApplicationManifest(),
                    occurred_at="2026-09-11T20:05:00Z",
                    explicit_request=True,
                )

    def test_stage_transitions_are_monotonic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            manifest, _ = start_packet(
                workspace,
                job_id,
                PacketOptions(cover_letter_enabled=False),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            with self.assertRaises(InvalidPacketTransition):
                advance_packet(manifest, job_id, "drafted", {"draft": "hash"})
            receipt = {
                "posting_url": "https://jobs.example/postings/SYN-601",
                "application_url": "https://jobs.example/apply/SYN-601",
            }
            advanced = advance_packet(manifest, job_id, "posting_verified", receipt)
            repeated = advance_packet(advanced, job_id, "posting_verified", receipt)
            self.assertEqual(advanced, repeated)

    def test_quality_stage_rejects_an_incomplete_gate_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            manifest, _ = start_packet(
                workspace,
                job_id,
                PacketOptions(cover_letter_enabled=False),
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
            manifest = advance_packet(
                manifest,
                job_id,
                "drafted",
                {"draft_hashes": {"resume": "a" * 64}},
            )
            with self.assertRaises(InvalidPacketTransition):
                advance_packet(manifest, job_id, "quality_checked", {"factual": True})

    def test_local_verification_completes_canonical_delivery_without_upload(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            manifest, record = start_packet(
                workspace,
                job_id,
                PacketOptions(cover_letter_enabled=False),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            actual_resume = workspace.root / record.resume_pdf
            actual_resume.write_bytes(b"%PDF-1.4\nsynthetic\n%%EOF\n")
            verification = verify_local_artifacts(workspace, record)
            manifest = advance_to_saved(manifest, job_id, verification.hashes)
            completed = complete_local_delivery(
                workspace,
                manifest,
                job_id,
                occurred_at="2026-09-11T20:10:00Z",
            )

            self.assertTrue(verification.valid)
            self.assertEqual(completed.packets[job_id][-1].stage, "ready")
            canonical = read_job(workspace, job_id)
            self.assertEqual(canonical["status"], "packet_ready")
            self.assertEqual(canonical["application_versions"][0]["version"], "v001")
            self.assertEqual(
                canonical["application_versions"][0]["resume_pdf"],
                record.resume_pdf.as_posix(),
            )
            persisted = load_manifest(
                workspace.state / "application-manifest.json"
            )
            self.assertEqual(persisted.packets[job_id][-1].stage, "ready")


if __name__ == "__main__":
    unittest.main()
