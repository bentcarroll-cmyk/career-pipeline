import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from career_pipeline.packets import (
    ApplicationManifest, InvalidPacketTransition, advance_packet, collect_local_artifacts,
    complete_local_delivery, load_manifest, save_manifest, start_packet, verify_local_artifacts,
)
from career_pipeline.quality import QualityReceipt
from career_pipeline.resume_layout import LayoutMeasurementError, measure_resume_layout
from career_pipeline.workspace import create_workspace
from tests.pdf_helper import write_minimal_pdf, write_text_pdf
from tests.unit.test_packets import advance_to_saved, bound_quality_receipt, seed_job, synthetic_packet_options


class ResumeLayoutRegressionTests(unittest.TestCase):
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

    @staticmethod
    def body_lines(count=49, size=11):
        return [(48, 56 + n * 14, size, "Supported synthetic responsibility and outcome.") for n in range(count)]

    def drafted(self):
        manifest = advance_packet(self.manifest, self.job_id, "posting_verified", {
            "posting_url": "https://example.com/job", "application_url": "https://example.com/apply",
            "posting_snapshot_hash": "b" * 64,
        })
        return advance_packet(manifest, self.job_id, "drafted", {"draft_hashes": {"resume": "a" * 64}})

    def saved(self):
        return advance_to_saved(self.workspace, self.manifest, self.job_id,
                                collect_local_artifacts(self.workspace, self.record).hashes)

    def test_empty_two_page_resume_is_rejected(self):
        write_minimal_pdf(self.pdf, pages=2)
        actual = collect_local_artifacts(self.workspace, self.record)
        self.assertFalse(actual.valid, "Two empty pages must never satisfy packet verification")

    def test_sparse_two_page_resume_is_rejected(self):
        lines = [(48, 56 + n * 14, 11, "Supported synthetic responsibility and outcome.") for n in range(30)]
        write_text_pdf(self.pdf, lines_by_page=[lines, lines])
        actual = collect_local_artifacts(self.workspace, self.record)
        self.assertFalse(actual.valid, "A resume ending near two thirds of each page must fail")

    def test_actual_one_page_resume_is_rejected(self):
        write_text_pdf(self.pdf, pages=1)
        actual = collect_local_artifacts(self.workspace, self.record)
        self.assertFalse(actual.valid, "The PDF page count must match the required two pages")

    def test_balanced_resume_passes_and_receipt_matches_final_bytes(self):
        write_text_pdf(self.pdf)
        receipt = measure_resume_layout(self.pdf)
        self.assertTrue(receipt["passed"], receipt["errors"])
        self.assertEqual(receipt["pdf_sha256"], hashlib.sha256(self.pdf.read_bytes()).hexdigest())
        self.assertEqual(receipt, measure_resume_layout(self.pdf))
        completed = complete_local_delivery(self.workspace, self.saved(), self.job_id,
                                            occurred_at="2026-09-15T12:10:00Z")
        self.assertEqual(completed.packets[self.job_id][-1].stage, "ready")

    def test_one_dense_page_does_not_compensate_for_sparse_page(self):
        write_text_pdf(self.pdf, lines_by_page=[self.body_lines(), self.body_lines(30)])
        receipt = measure_resume_layout(self.pdf)
        self.assertIn("page_2_bottom_gap_exceeds_limit", receipt["errors"])
        self.assertNotIn("page_1_bottom_gap_exceeds_limit", receipt["errors"])

    def test_page_number_footer_cannot_disguise_sparse_body(self):
        for footer in ("2", "Page 2 of 2", "Synthetic Candidate | Page 2"):
            with self.subTest(footer=footer):
                lines = self.body_lines(30) + [(48, 734, 10, footer)]
                write_text_pdf(self.pdf, lines_by_page=[self.body_lines(), lines])
                report = measure_resume_layout(self.pdf)
                self.assertIn("page_2_bottom_gap_exceeds_limit", report["errors"])
                self.assertGreater(report["pages"][1]["excluded_running_or_outside_body_glyph_count"], 0)

    def test_substantive_year_after_separator_counts_as_body_text(self):
        degree = "Bachelor of Science in Operations | 2011"
        lines = self.body_lines() + [(48, 740, 9.5, degree)]
        write_text_pdf(self.pdf, lines_by_page=[self.body_lines(), lines])
        report = measure_resume_layout(self.pdf)
        self.assertIn("page_2_body_font_too_small", report["errors"])
        self.assertEqual(report["pages"][1]["excluded_running_or_outside_body_glyph_count"], 0)

    def test_only_the_actual_page_number_and_total_are_running_text(self):
        for footer in ("Candidate | 1", "Candidate | 3", "Page 2 of 2011"):
            with self.subTest(footer=footer):
                lines = self.body_lines() + [(48, 740, 9.5, footer)]
                write_text_pdf(self.pdf, lines_by_page=[self.body_lines(), lines])
                report = measure_resume_layout(self.pdf)
                self.assertIn("page_2_body_font_too_small", report["errors"])

    def test_outside_footer_does_not_count_toward_fullness(self):
        lines = self.body_lines(30) + [(48, 774, 8.5, "Synthetic Candidate")]
        write_text_pdf(self.pdf, lines_by_page=[lines, lines])
        self.assertIn("page_1_bottom_gap_exceeds_limit", measure_resume_layout(self.pdf)["errors"])

    def test_substantive_text_in_margin_is_overflow_not_running_footer(self):
        lines = self.body_lines() + [(48, 774, 11, "This is substantive experience that overflows the body.")]
        write_text_pdf(self.pdf, lines_by_page=[lines, lines])
        self.assertIn("page_1_unclassified_text_outside_body", measure_resume_layout(self.pdf)["errors"])

    def test_large_internal_gap_fails_even_with_text_near_bottom(self):
        lines = self.body_lines()
        lines = lines[:20] + lines[30:]
        write_text_pdf(self.pdf, lines_by_page=[lines, lines])
        report = measure_resume_layout(self.pdf)
        self.assertIn("page_1_internal_gap_exceeds_limit", report["errors"])
        self.assertLess(report["pages"][0]["blank_bottom_pt"], 38.1)

    def test_tiny_or_inflated_body_type_fails(self):
        for size, reason in ((9.5, "body_font_too_small"), (15, "body_font_inflated")):
            with self.subTest(size=size):
                write_text_pdf(self.pdf, lines_by_page=[self.body_lines(size=size)] * 2)
                self.assertIn(f"page_1_{reason}", measure_resume_layout(self.pdf)["errors"])

    def test_geometry_errors_fail_closed(self):
        for settings in ({"page_size": (595, 842)}, {"rotation": 90}):
            with self.subTest(settings=settings):
                write_text_pdf(self.pdf, **settings)
                with self.assertRaisesRegex(LayoutMeasurementError, "geometry"):
                    measure_resume_layout(self.pdf)

    def test_missing_dependency_has_actionable_error(self):
        write_text_pdf(self.pdf)
        with patch("career_pipeline.resume_layout.importlib.import_module", side_effect=ImportError):
            with self.assertRaisesRegex(LayoutMeasurementError, "pdfplumber_unavailable.*bundled Python"):
                measure_resume_layout(self.pdf)
            self.assertFalse(collect_local_artifacts(self.workspace, self.record).valid)

    def test_invisible_text_rendering_mode_cannot_fill_pages(self):
        write_text_pdf(self.pdf, text_render_mode=3)
        with self.assertRaisesRegex(LayoutMeasurementError, "text_rendering_mode"):
            measure_resume_layout(self.pdf)

    def test_transparent_text_and_invisible_form_text_fail_closed(self):
        from reportlab.pdfgen.canvas import Canvas

        for in_form in (False, True):
            with self.subTest(in_form=in_form):
                document = Canvas(str(self.pdf), pagesize=(612, 792))
                for page in range(2):
                    if in_form:
                        document.beginForm(f"hidden{page}")
                    else:
                        document.setFillAlpha(0)
                    text = document.beginText()
                    text.setFont("Helvetica", 11)
                    if in_form:
                        text.setTextRenderMode(3)
                    for _, baseline, _, value in self.body_lines():
                        text.setTextOrigin(48, 792 - baseline)
                        text.textOut(value)
                    document.drawText(text)
                    if in_form:
                        document.endForm()
                        document.doForm(f"hidden{page}")
                    document.showPage()
                document.save()
                with self.assertRaises(LayoutMeasurementError):
                    measure_resume_layout(self.pdf)

    def test_self_attested_flags_without_layout_cannot_advance(self):
        write_text_pdf(self.pdf)
        manifest = self.drafted()
        receipt = bound_quality_receipt(self.workspace, manifest.packets[self.job_id][-1],
                                        collect_local_artifacts(self.workspace, self.record).hashes)
        receipt.pop("resume_layout")
        with self.assertRaisesRegex(InvalidPacketTransition, "resume_layout_missing"):
            advance_packet(manifest, self.job_id, "quality_checked", receipt, workspace=self.workspace)

    def test_forged_pass_receipt_is_remeasured(self):
        write_text_pdf(self.pdf)
        manifest = self.drafted()
        good = bound_quality_receipt(self.workspace, manifest.packets[self.job_id][-1],
                                    collect_local_artifacts(self.workspace, self.record).hashes)
        write_text_pdf(self.pdf, lines_by_page=[self.body_lines(30)] * 2)
        digest = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        good["bindings"]["final_pdf_hashes"]["resume"] = digest
        good["resume_layout"]["pdf_sha256"] = digest
        with self.assertRaisesRegex(InvalidPacketTransition, "bottom_gap_exceeds_limit"):
            advance_packet(manifest, self.job_id, "quality_checked", good, workspace=self.workspace)

    def test_pdf_changed_after_measurement_cannot_advance_or_resume_delivery(self):
        write_text_pdf(self.pdf)
        saved = self.saved()
        old = saved.packets[self.job_id][-1]
        write_text_pdf(self.pdf, lines_by_page=[self.body_lines(30)] * 2)
        with self.assertRaisesRegex(InvalidPacketTransition, "bottom_gap_exceeds_limit"):
            complete_local_delivery(self.workspace, saved, self.job_id, occurred_at="2026-09-15T12:10:00Z")
        self.assertFalse(verify_local_artifacts(self.workspace, old).valid)

    def test_repeated_quality_checkpoint_rechecks_actual_pdf(self):
        write_text_pdf(self.pdf)
        manifest = self.drafted()
        receipt = bound_quality_receipt(self.workspace, manifest.packets[self.job_id][-1],
                                        collect_local_artifacts(self.workspace, self.record).hashes)
        checked = advance_packet(manifest, self.job_id, "quality_checked", receipt, workspace=self.workspace)
        write_text_pdf(self.pdf, lines_by_page=[self.body_lines(30)] * 2)
        with self.assertRaisesRegex(InvalidPacketTransition, "bottom_gap_exceeds_limit"):
            advance_packet(checked, self.job_id, "quality_checked", receipt, workspace=self.workspace)

    def test_historical_receipt_without_layout_loads_but_cannot_resume_delivery(self):
        write_text_pdf(self.pdf)
        saved = self.saved()
        record = saved.packets[self.job_id][-1]
        receipts = deepcopy(record.receipts)
        receipts["quality_checked"].pop("resume_layout")
        legacy = replace(saved, packets={self.job_id: (replace(record, receipts=receipts),)})
        path = self.workspace.state / "application-manifest.json"
        save_manifest(path, legacy)
        loaded = load_manifest(path)
        self.assertEqual(loaded.packets[self.job_id][-1].stage, "saved")
        with self.assertRaisesRegex(InvalidPacketTransition, "resume_layout_missing"):
            complete_local_delivery(self.workspace, loaded, self.job_id, occurred_at="2026-09-15T12:10:00Z")

    def test_cli_returns_failure_and_writes_measurements_for_sparse_pdf(self):
        write_text_pdf(self.pdf, lines_by_page=[self.body_lines(30)] * 2)
        script = Path(__file__).resolve().parents[2] / "scripts" / "measure_resume_layout.py"
        output = self.workspace.root / "layout.json"
        result = subprocess.run([sys.executable, str(script), "--pdf", str(self.pdf), "--output", str(output)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(output.read_text())["passed"])


if __name__ == "__main__":
    unittest.main()
