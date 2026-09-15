from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from career_pipeline.job_store import read_job, update_job_status
from career_pipeline.packets import (
    ApplicationManifest, InvalidPacketTransition, advance_packet, collect_local_artifacts,
    complete_local_delivery, load_manifest, save_manifest, start_packet,
    persist_manifest, revalidate_legacy_packet_layout, validate_packet_history, verify_local_artifacts,
)
from career_pipeline.workspace import create_workspace
from tests.pdf_helper import write_text_pdf
from tests.unit.test_packets import advance_to_saved, seed_job, synthetic_packet_options


class LegacyPacketRevalidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = create_workspace(Path(self.temporary.name) / "Synthetic-Career")
        self.job_id = seed_job(self.workspace)
        self.manifest, self.record = start_packet(
            self.workspace, self.job_id, synthetic_packet_options(), ApplicationManifest(),
            occurred_at="2026-09-15T12:00:00Z", explicit_request=True,
        )
        self.pdf = self.workspace.root / self.record.resume_pdf
        write_text_pdf(self.pdf)
        self.hashes = collect_local_artifacts(self.workspace, self.record).hashes
        self.manifest = advance_to_saved(self.workspace, self.manifest, self.job_id, self.hashes)
        self.manifest_path = self.workspace.state / "application-manifest.json"
        self.script = Path(__file__).resolve().parents[2] / "scripts" / "update_packet.py"

    def legacy(self, stage="saved"):
        if stage == "local_verified":
            self.manifest = advance_packet(self.manifest, self.job_id, stage, {
                "verified": True, "artifact_hashes": dict(self.hashes),
            })
        elif stage == "ready":
            self.manifest = complete_local_delivery(self.workspace, self.manifest, self.job_id,
                occurred_at="2026-09-15T12:03:00Z")
        record = self.manifest.packets[self.job_id][-1]
        receipts = deepcopy(record.receipts)
        receipts["quality_checked"].pop("resume_layout")
        if stage == "quality_checked":
            receipts.pop("saved")
        self.original_receipts = deepcopy(receipts)
        self.record = replace(record, stage=stage, receipts=receipts)
        self.manifest = replace(self.manifest, packets={self.job_id: (self.record,)})
        save_manifest(self.manifest_path, self.manifest)

    def run_cli(self, occurred_at="2026-09-15T12:05:00Z", python_flags=()):
        return subprocess.run([
            sys.executable, *python_flags, str(self.script), "--workspace", str(self.workspace.root),
            "--job-id", self.job_id, "--stage", "revalidate-layout",
            "--reviewer", "Synthetic reviewer", "--occurred-at", occurred_at,
        ], capture_output=True, text=True, check=False)

    def test_cli_recovers_saved_packet_without_replacing_reviews_or_job_state(self):
        self.legacy()
        original_job = read_job(self.workspace, self.job_id)

        result = self.run_cli()

        self.assertEqual(result.returncode, 0, result.stderr)
        recovered = load_manifest(self.manifest_path)
        record = recovered.packets[self.job_id][-1]
        self.assertEqual((record.version, record.stage), ("v001", "saved"))
        self.assertEqual(read_job(self.workspace, self.job_id), original_job)
        for name, receipt in self.original_receipts.items():
            self.assertEqual(record.receipts[name], receipt)
        self.assertIn("layout_revalidated", record.receipts)
        validate_packet_history(record)
        self.assertTrue(verify_local_artifacts(self.workspace, record).valid)
        completed = complete_local_delivery(self.workspace, recovered, self.job_id,
            occurred_at="2026-09-15T12:10:00Z")
        self.assertEqual(completed.packets[self.job_id][-1].stage, "ready")
        self.assertEqual(len(completed.packets[self.job_id]), 1)
        canonical = read_job(self.workspace, self.job_id)
        self.assertEqual(canonical["status"], "packet_ready")
        self.assertEqual([item["version"] for item in canonical["application_versions"]], ["v001"])

    def test_local_verified_retries_reuse_the_audit_and_preserve_applied_status(self):
        self.legacy("local_verified")
        update_job_status(self.workspace, self.job_id, "applied", occurred_at="2026-09-15T12:04:00Z")
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        first_bytes = self.manifest_path.read_bytes()
        retry = self.run_cli(occurred_at="2026-09-15T12:06:00Z")
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertEqual(self.manifest_path.read_bytes(), first_bytes)
        recovered = load_manifest(self.manifest_path)
        for _ in range(2):
            recovered = complete_local_delivery(self.workspace, recovered, self.job_id,
                occurred_at="2026-09-15T12:10:00Z")
        self.assertEqual(read_job(self.workspace, self.job_id)["status"], "applied")
        self.assertEqual(len(read_job(self.workspace, self.job_id)["application_versions"]), 1)

    def test_quality_checked_packet_can_recover_then_save_and_deliver(self):
        self.legacy("quality_checked")
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        recovered = load_manifest(self.manifest_path)
        saved = advance_packet(recovered, self.job_id, "saved", {"artifact_hashes": dict(self.hashes)})
        completed = complete_local_delivery(self.workspace, saved, self.job_id,
            occurred_at="2026-09-15T12:10:00Z")
        self.assertEqual(completed.packets[self.job_id][-1].stage, "ready")

    def test_ready_packet_revalidation_does_not_rewrite_canonical_delivery(self):
        self.legacy("ready")
        before = read_job(self.workspace, self.job_id)
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(read_job(self.workspace, self.job_id), before)
        self.assertTrue(verify_local_artifacts(self.workspace,
            load_manifest(self.manifest_path).packets[self.job_id][-1]).valid)

    def test_modern_quality_receipt_cannot_use_legacy_revalidation(self):
        save_manifest(self.manifest_path, self.manifest)
        before = self.manifest_path.read_bytes()
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("only for legacy receipts", result.stderr)
        self.assertEqual(self.manifest_path.read_bytes(), before)

    def test_missing_editorial_approval_and_wrong_input_binding_are_not_refreshed(self):
        self.legacy()
        raw = json.loads(self.manifest_path.read_text())
        for change in ("factual", "profile_hash", "bindings"):
            with self.subTest(change=change):
                altered = deepcopy(raw)
                quality = altered["packets"][self.job_id][0]["receipts"]["quality_checked"]
                if change == "factual":
                    quality["factual"] = False
                elif change == "profile_hash":
                    quality["bindings"]["profile_hash"] = "different-approved-profile"
                else:
                    quality.pop("bindings")
                self.manifest_path.write_text(json.dumps(altered))
                before = self.manifest_path.read_bytes()
                result = self.run_cli()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.manifest_path.read_bytes(), before)
                self.assertEqual(read_job(self.workspace, self.job_id)["application_versions"], [])

    def test_changed_but_balanced_pdf_cannot_reuse_original_editorial_approval(self):
        self.legacy()
        before = self.manifest_path.read_bytes()
        lines = [(48, 56 + n * 14, 11, "Different supported synthetic evidence.") for n in range(49)]
        write_text_pdf(self.pdf, lines_by_page=[lines, lines])
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("original quality receipt", result.stderr)
        self.assertEqual(self.manifest_path.read_bytes(), before)

    def test_sparse_pdf_and_missing_dependency_do_not_record_an_audit(self):
        self.legacy()
        before = self.manifest_path.read_bytes()
        missing_dependency = self.run_cli(python_flags=("-S",))
        self.assertNotEqual(missing_dependency.returncode, 0)
        self.assertIn("pdfplumber_unavailable", missing_dependency.stderr)
        self.assertEqual(self.manifest_path.read_bytes(), before)
        lines = [(48, 56 + n * 14, 11, "Supported synthetic evidence.") for n in range(20)]
        write_text_pdf(self.pdf, lines_by_page=[lines, lines])
        sparse = self.run_cli()
        self.assertNotEqual(sparse.returncode, 0)
        self.assertIn("bottom_gap_exceeds_limit", sparse.stderr)
        self.assertEqual(self.manifest_path.read_bytes(), before)

    def test_audit_retry_and_delivery_reject_files_changed_after_revalidation(self):
        self.legacy()
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        before = self.manifest_path.read_bytes()
        lines = [(48, 56 + n * 14, 11, "Changed after audit; still a balanced PDF.") for n in range(49)]
        write_text_pdf(self.pdf, lines_by_page=[lines, lines])
        retry = self.run_cli()
        self.assertNotEqual(retry.returncode, 0)
        self.assertIn("resume_hash_mismatch", retry.stderr)
        with self.assertRaises(InvalidPacketTransition):
            complete_local_delivery(self.workspace, load_manifest(self.manifest_path), self.job_id,
                occurred_at="2026-09-15T12:10:00Z")
        self.assertEqual(self.manifest_path.read_bytes(), before)
        self.assertEqual(read_job(self.workspace, self.job_id)["application_versions"], [])

    def test_stale_progress_merge_preserves_audit_and_rejects_conflicting_audit(self):
        self.legacy()
        stale = self.manifest
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        recovered = load_manifest(self.manifest_path)
        audit = deepcopy(recovered.packets[self.job_id][-1].receipts["layout_revalidated"])
        progressed = advance_packet(stale, self.job_id, "local_verified", {
            "verified": True, "artifact_hashes": dict(self.hashes),
        })
        merged = persist_manifest(self.workspace, progressed)
        self.assertEqual(merged.packets[self.job_id][-1].receipts["layout_revalidated"], audit)
        self.assertEqual(persist_manifest(self.workspace, stale), merged)
        record = merged.packets[self.job_id][-1]
        receipts = deepcopy(record.receipts)
        receipts["layout_revalidated"]["reviewer"] = "Conflicting reviewer"
        conflicting = replace(merged, packets={self.job_id: (replace(record, receipts=receipts),)})
        with self.assertRaisesRegex(InvalidPacketTransition, "revalidation receipt conflicts"):
            persist_manifest(self.workspace, conflicting)

    def test_arbitrary_same_stage_receipt_injection_remains_rejected(self):
        self.legacy()
        injected = replace(self.record, receipts={**self.record.receipts, "unapproved": {"pass": True}})
        with self.assertRaises(InvalidPacketTransition):
            persist_manifest(self.workspace, replace(self.manifest, packets={self.job_id: (injected,)}))

    def test_changed_original_review_and_forged_measurement_fail_validation(self):
        self.legacy()
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        recovered = load_manifest(self.manifest_path)
        record = recovered.packets[self.job_id][-1]
        for change in ("quality", "measurement", "modern"):
            with self.subTest(change=change):
                receipts = deepcopy(record.receipts)
                if change == "quality":
                    receipts["quality_checked"]["review_note"] = "Changed after the recorded audit"
                elif change == "measurement":
                    receipts["layout_revalidated"]["resume_layout"]["pages"][0]["blank_bottom_pt"] = 0
                else:
                    receipts["quality_checked"]["resume_layout"] = deepcopy(receipts["layout_revalidated"]["resume_layout"])
                altered = replace(record, receipts=receipts)
                self.assertFalse(verify_local_artifacts(self.workspace, altered).valid)
                if change != "measurement":
                    with self.assertRaises(InvalidPacketTransition):
                        validate_packet_history(altered)

    def test_changed_cover_letter_cannot_reuse_original_editorial_approval(self):
        record = self.manifest.packets[self.job_id][-1]
        cover = record.version_dir / "Cover_Letter_Synthetic.pdf"
        write_text_pdf(self.workspace.root / cover, pages=1)
        cover_hash = hashlib.sha256((self.workspace.root / cover).read_bytes()).hexdigest()
        receipts = deepcopy(record.receipts)
        options = {**record.packet_options, "cover_letter_enabled": True, "cover_letter_pages": 1}
        receipts["selected"]["packet_options"] = options
        receipts["drafted"]["draft_hashes"]["cover_letter"] = "c" * 64
        quality = receipts["quality_checked"]
        quality["cover_letter_pages"] = 1
        quality["bindings"]["packet_options"] = options
        quality["bindings"]["draft_hashes"] = dict(receipts["drafted"]["draft_hashes"])
        quality["bindings"]["final_pdf_hashes"]["cover_letter"] = cover_hash
        receipts["saved"]["artifact_hashes"]["cover_letter"] = cover_hash
        record = replace(record, cover_letter_pdf=cover, packet_options=options, receipts=receipts)
        validate_packet_history(record)
        self.manifest = replace(self.manifest, packets={self.job_id: (record,)})
        self.legacy()
        write_text_pdf(self.workspace.root / cover, lines_by_page=[[(48, 56, 11, "Changed cover letter.")]])
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("original quality receipt", result.stderr)

    def test_superseded_packet_revalidation_cannot_touch_latest_version(self):
        self.legacy()
        stale = self.manifest
        latest, _ = start_packet(self.workspace, self.job_id, synthetic_packet_options(), self.manifest,
            occurred_at="2026-09-15T12:04:00Z", explicit_request=True, restart=True)
        with self.assertRaisesRegex(InvalidPacketTransition, "superseded"):
            revalidate_legacy_packet_layout(self.workspace, stale, self.job_id,
                reviewer="Synthetic reviewer", occurred_at="2026-09-15T12:05:00Z")
        self.assertEqual(load_manifest(self.manifest_path), latest)


if __name__ == "__main__":
    unittest.main()
