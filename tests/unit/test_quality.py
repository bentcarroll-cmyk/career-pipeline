import unittest
from dataclasses import replace
from pathlib import Path
import tempfile

import career_pipeline.quality as quality
from career_pipeline.quality import QualityReceipt, validate_quality_receipt
from career_pipeline.resume_layout import measure_resume_layout
from tests.pdf_helper import write_text_pdf


class QualityGateTests(unittest.TestCase):
    def measured_layout(self):
        with tempfile.TemporaryDirectory() as raw:
            pdf = Path(raw) / "resume.pdf"
            write_text_pdf(pdf)
            return measure_resume_layout(pdf)

    def test_resume_identity_rejects_exact_target_title_before_first_section(self) -> None:
        resume_text = """SYNTHETIC CANDIDATE
Anywhere, US | synthetic contact
Staff Product Manager | Headway
EXECUTIVE PROFILE
Product and operations leader with 15 years of experience.
"""

        validator = getattr(
            quality,
            "validate_resume_identity_header",
            lambda *_args, **_kwargs: (),
        )
        self.assertEqual(
            validator(
                resume_text,
                employer="Headway (NY)",
                title="Staff Product Manager",
            ),
            ("target_role_title_in_resume_header",),
        )

    def test_resume_identity_allows_capability_headline_containing_generic_title_word(self) -> None:
        resume_text = """SYNTHETIC CANDIDATE
Anywhere, US | synthetic contact
AI TRANSFORMATION | BUSINESS OPERATIONS | TEAM LEADERSHIP
EXECUTIVE PROFILE
Operations leader with 15 years of experience.
"""

        self.assertEqual(
            quality.validate_resume_identity_header(
                resume_text,
                employer="Synthetic Employer",
                title="Operations",
            ),
            (),
        )

    def test_resume_identity_rejects_target_employer_as_identity_line(self) -> None:
        resume_text = """SYNTHETIC CANDIDATE
Anywhere, US | synthetic contact
Headway
EXECUTIVE PROFILE
Product and operations leader.
"""

        self.assertEqual(
            quality.validate_resume_identity_header(
                resume_text,
                employer="Headway",
                title="Staff Product Manager",
            ),
            ("target_employer_in_resume_header",),
        )

    def test_resume_identity_does_not_scan_work_history_under_conventional_headings(self) -> None:
        for heading in (
            "PROFESSIONAL SUMMARY", "WORK EXPERIENCE", "WORK HISTORY",
            "EMPLOYMENT HISTORY", "CAREER SUMMARY", "PROFESSIONAL PROFILE",
            "RELEVANT EXPERIENCE", "CAREER HISTORY",
        ):
            with self.subTest(heading=heading):
                text = (
                    "SYNTHETIC CANDIDATE\nPRODUCT STRATEGY | CUSTOMER DISCOVERY\n"
                    f"{heading}:\nPrior Company, 2020-2025\nStaff Product Manager\n"
                    "Led product launches.\n"
                )
                self.assertEqual(quality.validate_resume_identity_header(
                    text, employer="Target Company", title="Staff Product Manager",
                ), ())

    def test_resume_identity_rejects_target_title_wrapped_across_header_lines(self) -> None:
        for headline in (
            "Senior Director, Strategy and\nOperations",
            "Senior Director,\nStrategy and\nOperations | Target Company",
            "Target Company | Senior Director, Strategy and\nOperations",
        ):
            with self.subTest(headline=headline):
                text = f"SYNTHETIC CANDIDATE\n{headline}\nPROFESSIONAL SUMMARY\nLeader.\n"
                self.assertEqual(quality.validate_resume_identity_header(
                    text, employer="Target Company", title="Senior Director, Strategy and Operations",
                ), ("target_role_title_in_resume_header",))

    def test_resume_identity_does_not_join_header_to_section_content(self) -> None:
        text = (
            "SYNTHETIC CANDIDATE\nSenior Director, Strategy and\n"
            "PROFESSIONAL SUMMARY\nOperations leadership and customer discovery.\n"
        )
        self.assertEqual(quality.validate_resume_identity_header(
            text, employer="Target Company", title="Senior Director, Strategy and Operations",
        ), ())

    def test_resume_content_rejects_requested_start_date_anywhere(self) -> None:
        resume_text = """SYNTHETIC CANDIDATE
Anywhere, US | synthetic contact
AI TRANSFORMATION | OPERATING MODELS | ADOPTION
EXECUTIVE PROFILE
Operations leader with 15 years of experience.
ADDITIONAL
U.S. citizen; no sponsorship required. Preferred start date: January 5, 2027.
"""

        validator = getattr(
            quality,
            "validate_resume_start_date",
            lambda *_args, **_kwargs: (),
        )
        self.assertEqual(
            validator(resume_text),
            ("requested_start_date_in_resume",),
        )

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
            resume_layout=self.measured_layout(),
        )
        self.assertEqual(
            validate_quality_receipt(receipt, cover_letter_enabled=True),
            ("visual",),
        )

    def test_cover_letter_opt_out_requires_no_cover_letter_pages(self) -> None:
        receipt = replace(QualityReceipt.all_passed(2, None), resume_layout=self.measured_layout())
        self.assertEqual(
            validate_quality_receipt(receipt, cover_letter_enabled=False),
            (),
        )

    def test_all_passed_flags_do_not_replace_independent_measurement(self) -> None:
        self.assertEqual(
            validate_quality_receipt(QualityReceipt.all_passed(2, None), cover_letter_enabled=False),
            ("resume_layout_missing",),
        )


if __name__ == "__main__":
    unittest.main()
