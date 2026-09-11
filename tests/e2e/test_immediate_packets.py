import tempfile
import unittest
from pathlib import Path

from career_pipeline.backlog import selection_from_request
from career_pipeline.packets import (
    ApplicationManifest,
    PacketOptions,
    PacketTicket,
    advance_packet,
    resume_queue,
    start_packet,
)
from career_pipeline.quality import QualityReceipt
from career_pipeline.workspace import create_workspace


def advance_to_ready(manifest, ticket_id):
    receipts = (
        ("posting_verified", {"posting_url": "posting", "application_url": "apply"}),
        ("drafted", {"draft_hashes": {"resume": "a" * 64}}),
        ("quality_checked", QualityReceipt.all_passed(2, None).as_dict()),
        ("saved", {"artifact_hashes": {"resume": "b" * 64}}),
        ("uploaded", {"attachment_ids": ["synthetic-attachment"]}),
        ("delivery_verified", {"verified": True, "attachment_hashes": {"resume": "b" * 64}}),
        ("ready", {"packet_ready": True}),
    )
    for stage, receipt in receipts:
        manifest = advance_packet(manifest, ticket_id, stage, receipt)
    return manifest


class ImmediatePacketTests(unittest.TestCase):
    def test_explicit_multi_role_request_starts_now_and_completed_work_does_not_resume(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            selection = selection_from_request(
                ("JOB-11", "JOB-12"),
                {},
                explicit_request=True,
            )
            manifest = ApplicationManifest()
            for ticket_id in selection.ticket_ids:
                manifest, record = start_packet(
                    PacketTicket(ticket_id, "Example Org", "Role", "posting", "apply"),
                    workspace,
                    PacketOptions(cover_letter_enabled=False),
                    manifest,
                )
                self.assertEqual(record.stage, "selected")
                manifest = advance_to_ready(manifest, ticket_id)
            self.assertEqual(resume_queue(manifest), ())

    def test_repeated_verified_stage_does_not_duplicate_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            manifest, _ = start_packet(
                PacketTicket("JOB-13", "Example Org", "Role", "posting", "apply"),
                workspace,
                PacketOptions(cover_letter_enabled=False),
                ApplicationManifest(),
            )
            receipt = {"posting_url": "posting", "application_url": "apply"}
            once = advance_packet(manifest, "JOB-13", "posting_verified", receipt)
            twice = advance_packet(once, "JOB-13", "posting_verified", receipt)
            self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
