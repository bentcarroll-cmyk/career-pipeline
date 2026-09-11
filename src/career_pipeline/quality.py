"""Deterministic validation for application-packet quality receipts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping


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
        )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def validate_quality_receipt(
    receipt: QualityReceipt,
    *,
    cover_letter_enabled: bool,
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
    return tuple(failures)
