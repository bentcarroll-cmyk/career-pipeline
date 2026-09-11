import tempfile
import unittest
import hashlib
from dataclasses import replace
from pathlib import Path

from career_pipeline.backlog import selection_from_request
from career_pipeline.job_store import create_job
from career_pipeline.packets import (
    ApplicationManifest,
    PacketOptions,
    advance_packet,
    complete_local_delivery,
    resume_queue,
    start_packet,
)
from career_pipeline.quality import QualityReceipt
from career_pipeline.workspace import create_workspace
from tests.unit.test_job_store import synthetic_assessment, synthetic_candidate


def seed_jobs(workspace) -> tuple[str, str]:
    ids = []
    for number in (1, 2):
        candidate = replace(
            synthetic_candidate(),
            source_record_id=f"synthetic-packet-{number}",
            requisition_id=f"SYN-PACKET-{number}",
            title=f"Operations Lead {number}",
            posting_url=f"https://jobs.example/postings/SYN-PACKET-{number}",
            application_url=f"https://jobs.example/apply/SYN-PACKET-{number}",
            raw_field_hash=f"{number:x}".rjust(64, "0"),
        )
        ids.append(
            create_job(
                workspace,
                candidate,
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T21:00:00Z",
            )["job_id"]
        )
    return tuple(ids)


def advance_to_ready(workspace, manifest, job_id):
    record = manifest.packets[job_id][-1]
    (workspace.root / record.resume_pdf).write_bytes(
        b"%PDF-1.4\nsynthetic\n%%EOF\n"
    )
    artifact_hash = hashlib.sha256(
        (workspace.root / record.resume_pdf).read_bytes()
    ).hexdigest()
    receipts = (
        (
            "posting_verified",
            {
                "posting_url": "https://jobs.example/postings/SYN-PACKET",
                "application_url": "https://jobs.example/apply/SYN-PACKET",
            },
        ),
        ("drafted", {"draft_hashes": {"resume": "a" * 64}}),
        ("quality_checked", QualityReceipt.all_passed(2, None).as_dict()),
        ("saved", {"artifact_hashes": {"resume": artifact_hash}}),
    )
    for stage, receipt in receipts:
        manifest = advance_packet(manifest, job_id, stage, receipt)
    return complete_local_delivery(
        workspace,
        manifest,
        job_id,
        occurred_at="2026-09-11T21:10:00Z",
    )


class ImmediatePacketTests(unittest.TestCase):
    def test_explicit_multi_role_request_starts_now_and_completes_locally(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_ids = seed_jobs(workspace)
            selection = selection_from_request(
                job_ids,
                {job_ids[1]: "Emphasize fictional operations evidence."},
                explicit_request=True,
                workspace=workspace,
            )
            manifest = ApplicationManifest()
            for job_id in selection.job_ids:
                manifest, record = start_packet(
                    workspace,
                    job_id,
                    PacketOptions(cover_letter_enabled=False),
                    manifest,
                    occurred_at="2026-09-11T21:05:00Z",
                    explicit_request=True,
                )
                self.assertEqual(record.stage, "selected")
                manifest = advance_to_ready(workspace, manifest, job_id)
            self.assertEqual(resume_queue(manifest), ())

    def test_repeated_verified_stage_does_not_duplicate_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_jobs(workspace)[0]
            manifest, _ = start_packet(
                workspace,
                job_id,
                PacketOptions(cover_letter_enabled=False),
                ApplicationManifest(),
                occurred_at="2026-09-11T21:05:00Z",
                explicit_request=True,
            )
            receipt = {
                "posting_url": "https://jobs.example/postings/SYN-PACKET-1",
                "application_url": "https://jobs.example/apply/SYN-PACKET-1",
            }
            once = advance_packet(manifest, job_id, "posting_verified", receipt)
            twice = advance_packet(once, job_id, "posting_verified", receipt)
            self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
