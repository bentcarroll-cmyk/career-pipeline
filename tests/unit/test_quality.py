import unittest

from career_pipeline.quality import QualityReceipt, validate_quality_receipt


class QualityGateTests(unittest.TestCase):
    def test_every_required_gate_and_page_count_must_pass(self) -> None:
        receipt = QualityReceipt(
            factual=True,
            chronology=True,
            tailoring=True,
            ats_structure=True,
            page_space=True,
            pdf_text=True,
            page_count=True,
            visual=False,
            resume_pages=2,
            cover_letter_pages=1,
        )
        self.assertEqual(
            validate_quality_receipt(receipt, cover_letter_enabled=True),
            ("visual",),
        )

    def test_cover_letter_opt_out_requires_no_cover_letter_pages(self) -> None:
        receipt = QualityReceipt.all_passed(2, None)
        self.assertEqual(
            validate_quality_receipt(receipt, cover_letter_enabled=False),
            (),
        )


if __name__ == "__main__":
    unittest.main()
