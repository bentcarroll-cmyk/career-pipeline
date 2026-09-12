import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from career_pipeline.job_store import create_job, read_job, update_job_status
from career_pipeline.packets import (
    ApplicationManifest,
    InvalidPacketTransition,
    PacketOptions,
    advance_packet,
    collect_local_artifacts,
    complete_local_delivery,
    load_manifest,
    start_packet,
    verify_local_artifacts,
)
from career_pipeline.quality import QualityReceipt
from career_pipeline.workspace import create_workspace
from tests.unit.test_job_store import synthetic_assessment, synthetic_candidate
from tests.pdf_helper import write_minimal_pdf


def synthetic_packet_options(**changes):
    values = {
        "cover_letter_enabled": False,
        "resume_pages": 2,
        "cover_letter_pages": 0,
        "profile_hash": "profile-hash-v1",
        "criteria_hash": "criteria-hash-v1",
        "writing_preferences_hash": "writing-preferences-hash-v1",
        "role_instructions": "Emphasize synthetic operating evidence.",
    }
    values.update(changes)
    return PacketOptions(**values)


def bound_quality_receipt(record, artifact_hashes):
    receipt = QualityReceipt.all_passed(
        2,
        1 if record.cover_letter_pdf is not None else None,
    ).as_dict()
    receipt["bindings"] = {
        "profile_hash": record.profile_hash,
        "criteria_hash": record.criteria_hash,
        "writing_preferences_hash": record.writing_preferences_hash,
        "packet_options": dict(record.packet_options),
        "role_instructions": record.role_instructions,
        "posting_snapshot_hash": record.receipts["posting_verified"][
            "posting_snapshot_hash"
        ],
        "draft_hashes": dict(record.receipts["drafted"]["draft_hashes"]),
        "final_pdf_hashes": dict(artifact_hashes),
    }
    return receipt


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
    manifest = advance_packet(
        manifest,
        job_id,
        "posting_verified",
        {
            "posting_url": "https://jobs.example/postings/SYN-601",
            "application_url": "https://jobs.example/apply/SYN-601",
            "posting_snapshot_hash": "b" * 64,
        },
    )
    manifest = advance_packet(
        manifest,
        job_id,
        "drafted",
        {"draft_hashes": {"resume": "a" * 64}},
    )
    record = manifest.packets[job_id][-1]
    manifest = advance_packet(
        manifest,
        job_id,
        "quality_checked",
        bound_quality_receipt(record, artifact_hashes),
    )
    manifest = advance_packet(
        manifest,
        job_id,
        "saved",
        {"artifact_hashes": artifact_hashes},
    )
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
                synthetic_packet_options(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            actual_resume = workspace.root / record.resume_pdf
            write_minimal_pdf(actual_resume, pages=2)
            verification = collect_local_artifacts(workspace, record)
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
                synthetic_packet_options(
                    cover_letter_enabled=True,
                    cover_letter_pages=1,
                ),
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
                    synthetic_packet_options(),
                    ApplicationManifest(),
                    occurred_at="2026-09-11T20:05:00Z",
                    explicit_request=False,
                )
            with self.assertRaises(InvalidPacketTransition):
                start_packet(
                    workspace,
                    "JOB-999999",
                    synthetic_packet_options(),
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
                synthetic_packet_options(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            with self.assertRaises(InvalidPacketTransition):
                advance_packet(manifest, job_id, "drafted", {"draft": "hash"})
            receipt = {
                "posting_url": "https://jobs.example/postings/SYN-601",
                "application_url": "https://jobs.example/apply/SYN-601",
                "posting_snapshot_hash": "b" * 64,
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
                synthetic_packet_options(),
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
                    "posting_snapshot_hash": "b" * 64,
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
                synthetic_packet_options(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            actual_resume = workspace.root / record.resume_pdf
            write_minimal_pdf(actual_resume, pages=2)
            verification = collect_local_artifacts(workspace, record)
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

    def test_quality_receipt_must_bind_inputs_drafts_posting_and_final_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            manifest, record = start_packet(
                workspace,
                job_id,
                synthetic_packet_options(),
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
                    "posting_snapshot_hash": "b" * 64,
                },
            )
            manifest = advance_packet(
                manifest,
                job_id,
                "drafted",
                {"draft_hashes": {"resume": "a" * 64}},
            )
            write_minimal_pdf(workspace.root / record.resume_pdf, pages=2)
            artifact_hashes = collect_local_artifacts(workspace, record).hashes
            receipt = bound_quality_receipt(
                manifest.packets[job_id][-1], artifact_hashes
            )
            receipt["bindings"] = {
                **receipt["bindings"],
                "criteria_hash": "wrong-criteria-hash",
            }

            with self.assertRaisesRegex(InvalidPacketTransition, "quality receipt binding"):
                advance_packet(manifest, job_id, "quality_checked", receipt)

    def test_ready_packet_verification_checks_recorded_hash_and_pdf_structure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            manifest, record = start_packet(
                workspace,
                job_id,
                synthetic_packet_options(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            resume = workspace.root / record.resume_pdf
            write_minimal_pdf(resume, pages=2)
            collected = collect_local_artifacts(workspace, record)
            manifest = advance_to_saved(manifest, job_id, collected.hashes)
            completed = complete_local_delivery(
                workspace,
                manifest,
                job_id,
                occurred_at="2026-09-11T20:10:00Z",
            )
            ready = completed.packets[job_id][-1]
            self.assertTrue(verify_local_artifacts(workspace, ready).valid)

            write_minimal_pdf(resume, pages=1)
            modified = verify_local_artifacts(workspace, ready)
            self.assertFalse(modified.valid)
            self.assertIn("resume_hash_mismatch", modified.errors)
            with self.assertRaisesRegex(
                InvalidPacketTransition, "local artifact checks failed"
            ):
                complete_local_delivery(
                    workspace,
                    completed,
                    job_id,
                    occurred_at="2026-09-11T20:11:00Z",
                )

            resume.write_bytes(b"%PDF-1.4\nnot a real PDF\n%%EOF\n")
            malformed = verify_local_artifacts(workspace, ready)
            self.assertFalse(malformed.valid)
            self.assertIn("resume_invalid_pdf", malformed.errors)

            resume.unlink()
            missing = verify_local_artifacts(workspace, ready)
            self.assertFalse(missing.valid)
            self.assertIn("resume_missing", missing.errors)

    def test_verification_rejects_unexpected_employer_facing_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            manifest, record = start_packet(
                workspace,
                job_id,
                synthetic_packet_options(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            write_minimal_pdf(workspace.root / record.resume_pdf, pages=2)
            write_minimal_pdf(workspace.root / record.version_dir / "unexpected.pdf")
            result = collect_local_artifacts(workspace, record)
            self.assertFalse(result.valid)
            self.assertIn("unexpected_employer_facing_pdf", result.errors)

    def test_legacy_manifest_without_input_bindings_remains_loadable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "legacy-manifest.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "packets": {
                            "JOB-000001": [
                                {
                                    "job_id": "JOB-000001",
                                    "employer": "Synthetic Example",
                                    "title": "Operations Lead",
                                    "version": "v001",
                                    "version_dir": "Applications/JOB-000001_Synthetic/v001",
                                    "resume_pdf": "Applications/JOB-000001_Synthetic/v001/Resume.pdf",
                                    "cover_letter_pdf": None,
                                    "working_dir": "Applications/JOB-000001_Synthetic/v001/working",
                                    "stage": "selected",
                                    "receipts": {},
                                    "profile_hash": "legacy-profile-hash",
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            record = load_manifest(path).packets["JOB-000001"][0]
            self.assertEqual(record.profile_hash, "legacy-profile-hash")
            self.assertIsNone(record.criteria_hash)
            self.assertFalse(record.packet_options["cover_letter_enabled"])

    def test_posting_and_draft_receipts_require_exact_sha256_identities(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            manifest, _ = start_packet(
                workspace,
                job_id,
                synthetic_packet_options(
                    cover_letter_enabled=True,
                    cover_letter_pages=1,
                ),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            posting_base = {
                "posting_url": "https://jobs.example/postings/SYN-601",
                "application_url": "https://jobs.example/apply/SYN-601",
            }
            for bad_hash in ("", "not-a-sha256", "g" * 64):
                with self.subTest(posting_snapshot_hash=bad_hash):
                    with self.assertRaisesRegex(
                        InvalidPacketTransition, "snapshot hash"
                    ):
                        advance_packet(
                            manifest,
                            job_id,
                            "posting_verified",
                            {**posting_base, "posting_snapshot_hash": bad_hash},
                        )

            posted = advance_packet(
                manifest,
                job_id,
                "posting_verified",
                {**posting_base, "posting_snapshot_hash": "b" * 64},
            )
            invalid_drafts = (
                {},
                {"resume": "a" * 64},
                {"resume": "bad", "cover_letter": "c" * 64},
                {
                    "resume": "a" * 64,
                    "cover_letter": "c" * 64,
                    "unexpected": "d" * 64,
                },
            )
            for draft_hashes in invalid_drafts:
                with self.subTest(draft_hashes=draft_hashes):
                    with self.assertRaisesRegex(
                        InvalidPacketTransition, "draft hashes"
                    ):
                        advance_packet(
                            posted,
                            job_id,
                            "drafted",
                            {"draft_hashes": draft_hashes},
                        )

    def test_pdf_structure_validation_works_without_site_packages(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "Synthetic-Career"
            workspace = create_workspace(root)
            job_id = seed_job(workspace)
            _, record = start_packet(
                workspace,
                job_id,
                synthetic_packet_options(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            write_minimal_pdf(workspace.root / record.resume_pdf, pages=2)
            source_root = Path(__file__).resolve().parents[2] / "src"
            script = "\n".join(
                (
                    "from pathlib import Path",
                    "from career_pipeline.packets import PacketRecord, collect_local_artifacts",
                    "from career_pipeline.workspace import workspace_paths",
                    f"root = Path({str(workspace.root)!r})",
                    f"relative = Path({record.resume_pdf.as_posix()!r})",
                    "record = PacketRecord(job_id='JOB-000001', employer='Synthetic', title='Lead', version='v001', version_dir=relative.parent, resume_pdf=relative, cover_letter_pdf=None, working_dir=relative.parent / 'working')",
                    "result = collect_local_artifacts(workspace_paths(root), record)",
                    "raise SystemExit(0 if result.valid else 1)",
                )
            )
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(source_root)

            result = subprocess.run(
                [sys.executable, "-S", "-c", script],
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
