"""Deterministic validation for application-packet quality receipts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Mapping

from .resume_layout import validate_layout_receipt


_RESUME_SECTION_HEADINGS = frozenset(
    {
        "additional",
        "career history",
        "career summary",
        "core capabilities",
        "education",
        "employment history",
        "executive profile",
        "experience",
        "professional experience",
        "professional profile",
        "professional summary",
        "relevant experience",
        "selected experience",
        "skills",
        "summary",
        "technical skills",
        "work experience",
        "work history",
    }
)


def _normalized_identity_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def validate_resume_identity_header(
    resume_text: str,
    *,
    employer: str,
    title: str,
) -> tuple[str, ...]:
    """Reject an exact target job title presented in the resume identity block."""

    normalized_title = _normalized_identity_text(title)
    normalized_employer = _normalized_identity_text(employer)
    normalized_employer_without_parenthetical = _normalized_identity_text(
        re.sub(r"\([^)]*\)", " ", employer)
    )
    employer_variants = {
        value
        for value in (normalized_employer, normalized_employer_without_parenthetical)
        if value
    }
    header_lines = []
    for raw_line in resume_text.splitlines():
        line = _normalized_identity_text(raw_line)
        if not line:
            continue
        if line in _RESUME_SECTION_HEADINGS:
            break
        header_lines.append(line)

    for index, line in enumerate(header_lines):
        # PDF extraction can wrap the headline. Join only text within the
        # identity block. A title must begin on this line, either at its start
        # or alongside the employer, so generic capability words elsewhere in
        # the header retain their existing meaning.
        remaining_header = " ".join(header_lines[index:])
        title_match = (
            re.search(rf"\b{re.escape(normalized_title)}\b", remaining_header)
            if normalized_title else None
        )
        if title_match and (
            title_match.start() == 0
            or (title_match.start() < len(line)
                and any(variant in line for variant in employer_variants)
            )
        ):
            return ("target_role_title_in_resume_header",)
        if line in employer_variants:
            return ("target_employer_in_resume_header",)
    return ()


def validate_resume_start_date(resume_text: str) -> tuple[str, ...]:
    """Reject candidate availability or requested start dates in a resume."""

    normalized = _normalized_identity_text(resume_text)
    patterns = (
        r"\b(?:preferred|requested|desired) start(?:ing)? date\b",
        r"\bavailable to start\b",
        r"\bavailability (?:date|to start)\b",
        r"\bearlier start negotiable\b",
    )
    if any(re.search(pattern, normalized) for pattern in patterns):
        return ("requested_start_date_in_resume",)
    return ()


@dataclass(frozen=True)
class QualityReceipt:
    factual: bool
    chronology: bool
    tailoring: bool
    ats_structure: bool
    page_space: bool
    pdf_text: bool
    page_count: bool
    visual: bool
    resume_pages: int
    cover_letter_pages: int | None
    resume_layout: Mapping[str, object] | None = None

    @classmethod
    def all_passed(
        cls,
        resume_pages: int,
        cover_letter_pages: int | None,
    ) -> "QualityReceipt":
        return cls(
            factual=True,
            chronology=True,
            tailoring=True,
            ats_structure=True,
            page_space=True,
            pdf_text=True,
            page_count=True,
            visual=True,
            resume_pages=resume_pages,
            cover_letter_pages=cover_letter_pages,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "QualityReceipt":
        return cls(
            factual=value["factual"] is True,
            chronology=value["chronology"] is True,
            tailoring=value["tailoring"] is True,
            ats_structure=value["ats_structure"] is True,
            page_space=value["page_space"] is True,
            pdf_text=value["pdf_text"] is True,
            page_count=value["page_count"] is True,
            visual=value["visual"] is True,
            resume_pages=int(value["resume_pages"]),
            cover_letter_pages=(
                int(value["cover_letter_pages"])
                if value.get("cover_letter_pages") is not None
                else None
            ),
            resume_layout=(value.get("resume_layout") if isinstance(value.get("resume_layout"), Mapping) else None),
        )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def validate_quality_receipt(
    receipt: QualityReceipt,
    *,
    cover_letter_enabled: bool,
    require_layout: bool = True,
) -> tuple[str, ...]:
    failures = [
        name
        for name in (
            "factual",
            "chronology",
            "tailoring",
            "ats_structure",
            "page_space",
            "pdf_text",
            "page_count",
            "visual",
        )
        if not getattr(receipt, name)
    ]
    if receipt.resume_pages != 2:
        failures.append("resume_page_count")
    expected_cover_pages = 1 if cover_letter_enabled else None
    if receipt.cover_letter_pages != expected_cover_pages:
        failures.append("cover_letter_page_count")
    if require_layout:
        failures.extend(validate_layout_receipt(receipt.resume_layout))
    return tuple(failures)
