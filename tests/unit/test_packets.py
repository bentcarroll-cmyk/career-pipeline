import tempfile
import unittest
from pathlib import Path

from career_pipeline.packets import (
    ApplicationManifest,
    InvalidPacketTransition,
    PacketOptions,
    PacketTicket,
    advance_packet,
    start_packet,
    verify_local_artifacts,
)
from career_pipeline.workspace import create_workspace


class PacketTests(unittest.TestCase):
    def test_final_pdfs_are_directly_browseable_in_v001(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            manifest, record = start_packet(
                PacketTicket(
                    "JOB-123",
                    "Example Organization",
                    "Operations Lead",
                    "https://jobs.example/postings/JOB-123",
                    "https://jobs.example/apply/JOB-123",
                ),
                workspace,
                PacketOptions(),
                ApplicationManifest(),
            )
            self.assertEqual(record.version, "v001")
            self.assertEqual(record.resume_pdf.parent, record.version_dir)
            self.assertEqual(record.cover_letter_pdf.parent, record.version_dir)
            self.assertEqual(record.working_dir.parent, record.version_dir)
            self.assertIn("JOB-123", manifest.packets)

    def test_stage_transitions_are_monotonic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            manifest, _ = start_packet(
                PacketTicket("JOB-1", "Example Org", "Role", "posting", "apply"),
                workspace,
                PacketOptions(cover_letter_enabled=False),
                ApplicationManifest(),
            )
            with self.assertRaises(InvalidPacketTransition):
                advance_packet(manifest, "JOB-1", "drafted", {"draft": "hash"})
            advanced = advance_packet(
                manifest,
                "JOB-1",
                "posting_verified",
                {"posting_url": "posting", "application_url": "apply"},
            )
            repeated = advance_packet(
                advanced,
                "JOB-1",
                "posting_verified",
                {"posting_url": "posting", "application_url": "apply"},
            )
            self.assertEqual(advanced, repeated)

    def test_quality_stage_rejects_an_incomplete_gate_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            manifest, _ = start_packet(
                PacketTicket("JOB-3", "Example Org", "Role", "posting", "apply"),
                workspace,
                PacketOptions(cover_letter_enabled=False),
                ApplicationManifest(),
            )
            manifest = advance_packet(
                manifest,
                "JOB-3",
                "posting_verified",
                {"posting_url": "posting", "application_url": "apply"},
            )
            manifest = advance_packet(
                manifest,
                "JOB-3",
                "drafted",
                {"draft_hashes": {"resume": "a" * 64}},
            )
            with self.assertRaises(InvalidPacketTransition):
                advance_packet(
                    manifest,
                    "JOB-3",
                    "quality_checked",
                    {"factual": True},
                )

    def test_artifact_verification_checks_pdf_hash_and_direct_parent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            manifest, record = start_packet(
                PacketTicket("JOB-2", "Example Org", "Role", "posting", "apply"),
                workspace,
                PacketOptions(cover_letter_enabled=False),
                ApplicationManifest(),
            )
            record.resume_pdf.write_bytes(b"%PDF-1.4\nsynthetic\n%%EOF\n")
            verification = verify_local_artifacts(record)
            self.assertTrue(verification.valid)
            self.assertIn("resume", verification.hashes)


if __name__ == "__main__":
    unittest.main()
