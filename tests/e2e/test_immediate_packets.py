import tempfile
import unittest
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
from tests.pdf_helper import write_text_pdf
from tests.unit.test_packets import (
    bound_quality_receipt,
    synthetic_packet_options,
)


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
    write_text_pdf(workspace.root / record.resume_pdf, pages=2)
    from career_pipeline.packets import collect_local_artifacts

    artifact_hashes = collect_local_artifacts(workspace, record).hashes
    manifest = advance_packet(
        manifest,
        job_id,
        "posting_verified",
        {
            "posting_url": "https://jobs.example/postings/SYN-PACKET",
            "application_url": "https://jobs.example/apply/SYN-PACKET",
            "posting_snapshot_hash": "b" * 64,
        },
    )
    manifest = advance_packet(
        manifest,
        job_id,
        "drafted",
        {"draft_hashes": {"resume": "a" * 64}},
    )
    manifest = advance_packet(
        manifest,
        job_id,
        "quality_checked",
        bound_quality_receipt(workspace, manifest.packets[job_id][-1], artifact_hashes),
        workspace=workspace,
    )
    manifest = advance_packet(
        manifest,
        job_id,
        "saved",
        {"artifact_hashes": artifact_hashes},
    )
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
                    synthetic_packet_options(
                        role_instructions=selection.per_role_instructions.get(job_id, ""),
                    ),
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
                synthetic_packet_options(),
                ApplicationManifest(),
                occurred_at="2026-09-11T21:05:00Z",
                explicit_request=True,
            )
            receipt = {
                "posting_url": "https://jobs.example/postings/SYN-PACKET-1",
                "application_url": "https://jobs.example/apply/SYN-PACKET-1",
                "posting_snapshot_hash": "b" * 64,
            }
            once = advance_packet(manifest, job_id, "posting_verified", receipt)
            twice = advance_packet(once, job_id, "posting_verified", receipt)
            self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
