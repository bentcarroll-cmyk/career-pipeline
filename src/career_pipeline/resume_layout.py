"""Measure final resume PDFs against a fixed, non-overridable layout policy.

Coordinates are PDF points from the top left. The supported page is US Letter
portrait, with a 41.75pt vertical body inset and 36pt horizontal safety inset.
These fixed bounds cannot be changed by a receipt or an inaccurate source DOCX.
This checks geometry and readable text, not factual support or editorial merit.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import math
from pathlib import Path
import re
import statistics
from typing import Mapping


POLICY_ID = "resume-layout-v1"
MAX_GAP_PT = 38.1
GEOMETRY = {
    "page_width_pt": 612.0,
    "page_height_pt": 792.0,
    "body_top_pt": 41.75,
    "body_bottom_pt": 750.25,
    "body_left_pt": 36.0,
    "body_right_pt": 576.0,
}
LIMITS = {
    "max_gap_pt": MAX_GAP_PT,
    "min_body_font_pt": 10.0,
    "max_median_body_font_pt": 14.0,
    "max_identity_font_pt": 24.0,
    "identity_bottom_pt": 90.0,
}
_EPSILON = 0.05
_PAGE_NUMBER = re.compile(
    r"(?:.+\s[|·•–—-]\s*)?(?:page\s*)?(?P<page>\d+)"
    r"(?:\s*(?:of|/)\s*(?P<total>\d+))?",
    re.IGNORECASE,
)


class LayoutMeasurementError(ValueError):
    """The final PDF could not be measured reliably; delivery must stop."""


def _require_supported_rendering(data: bytes) -> None:
    """Reject text visibility modes that glyph extraction cannot establish.

    pdfminer otherwise extracts invisible text as ordinary glyphs. Its nested
    Form interpreter inherits this subclass, so forms receive the same checks.
    """
    from pdfminer.pdfdevice import PDFDevice
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdftypes import dict_value, resolve1
    from pdfminer.psparser import literal_name

    class VisibleTextInterpreter(PDFPageInterpreter):
        def do_Tr(self, render):
            if resolve1(render) != 0:
                raise LayoutMeasurementError("unsupported_text_rendering_mode: use normal visible fill text")
            super().do_Tr(render)

        def do_gs(self, name):
            states = dict_value(self.resources.get("ExtGState", {}))
            state = dict_value(states.get(literal_name(name)))
            if not state:
                raise LayoutMeasurementError("unresolved_graphics_state")
            for key in ("ca", "CA"):
                if key in state and resolve1(state[key]) != 1:
                    raise LayoutMeasurementError("unsupported_transparent_graphics_state")
            if "SMask" in state and literal_name(resolve1(state["SMask"])) != "None":
                raise LayoutMeasurementError("unsupported_graphics_soft_mask")
            if "BM" in state and literal_name(resolve1(state["BM"])) not in {"Normal", "Compatible"}:
                raise LayoutMeasurementError("unsupported_graphics_blend_mode")
            super().do_gs(name)

    manager = PDFResourceManager()
    interpreter = VisibleTextInterpreter(manager, PDFDevice(manager))
    for page in PDFPage.get_pages(io.BytesIO(data)):
        interpreter.process_page(page)


def _rounded(value: float) -> float:
    return round(value, 4)


def _lines(chars: list[dict]) -> list[dict]:
    result: list[dict] = []
    for char in sorted(chars, key=lambda c: ((c["top"] + c["bottom"]) / 2, c["x0"])):
        center = (char["top"] + char["bottom"]) / 2
        if not result or abs(center - result[-1]["center"]) > 3:
            result.append({"center": center, "chars": [char]})
        else:
            result[-1]["chars"].append(char)
    for line in result:
        line["chars"].sort(key=lambda c: c["x0"])
        line["top"] = min(c["top"] for c in line["chars"])
        line["bottom"] = max(c["bottom"] for c in line["chars"])
        line["text"] = re.sub(r"\s+", " ", "".join(c["text"] for c in line["chars"])).strip()
    return result


def _white_text(char: Mapping[str, object]) -> bool:
    color = char.get("non_stroking_color")
    if isinstance(color, (float, int)):
        return color >= 0.98
    if isinstance(color, (tuple, list)):
        if len(color) in (1, 3):
            return all(isinstance(v, (float, int)) and v >= 0.98 for v in color)
        if len(color) == 4:
            return all(isinstance(v, (float, int)) and v <= 0.02 for v in color)
    return False


def _measure_page(page) -> dict[str, object]:
    errors: list[str] = []
    if (
        page.rotation
        or any(abs(float(value)) > 0.5 for value in page.bbox[:2])
        or abs(float(page.width) - GEOMETRY["page_width_pt"]) > 0.5
        or abs(float(page.height) - GEOMETRY["page_height_pt"]) > 0.5
        or any(abs(float(a) - float(b)) > 0.5 for a, b in zip(page.cropbox, page.mediabox))
    ):
        raise LayoutMeasurementError(f"page_{page.page_number}_unsupported_geometry")
    chars = [c for c in page.chars if c.get("text", "").strip()]
    for char in chars:
        if not all(
            isinstance(char.get(key), (int, float)) and math.isfinite(char[key])
            for key in ("x0", "x1", "top", "bottom", "size")
        ):
            raise LayoutMeasurementError(f"page_{page.page_number}_invalid_glyph_geometry")
        if not char.get("upright", True):
            raise LayoutMeasurementError(f"page_{page.page_number}_rotated_text")
        if char["x1"] <= char["x0"] or char["bottom"] <= char["top"]:
            errors.append("invalid_glyph_bounds")
        if char["x0"] < 0 or char["x1"] > page.width or char["top"] < 0 or char["bottom"] > page.height:
            errors.append("text_outside_page")

    # Common page numbers remain excluded even if a footer intrudes into the body.
    running_ids: set[int] = set()
    top, bottom = GEOMETRY["body_top_pt"], GEOMETRY["body_bottom_pt"]
    for line in _lines(page.chars):
        number_match = _PAGE_NUMBER.fullmatch(line["text"])
        page_number = (
            line["top"] > page.height / 2
            and number_match is not None
            and int(number_match["page"]) == page.page_number
            and (number_match["total"] is None or int(number_match["total"]) == 2)
        )
        small_margin_label = (
            (line["bottom"] <= top or line["top"] >= bottom)
            and len(line["text"]) <= 80
            and max(c["size"] for c in line["chars"]) <= 9.5 + _EPSILON
        )
        if page_number or small_margin_label:
            running_ids.update(id(char) for char in line["chars"])
    body = []
    excluded = 0
    for char in chars:
        if id(char) in running_ids:
            excluded += 1
            continue
        if char["bottom"] <= top or char["top"] >= bottom:
            excluded += 1
            errors.append("unclassified_text_outside_body")
            continue
        if char["top"] < top - _EPSILON or char["bottom"] > bottom + _EPSILON:
            errors.append("text_crosses_body_boundary")
        if char["x0"] < GEOMETRY["body_left_pt"] - _EPSILON or char["x1"] > GEOMETRY["body_right_pt"] + _EPSILON:
            errors.append("text_crosses_horizontal_safety_margin")
        if _white_text(char):
            errors.append("white_or_nearly_white_body_text")
            continue
        body.append(char)

    result: dict[str, object] = {
        "page_number": page.page_number,
        "body_glyph_count": len(body),
        "excluded_running_or_outside_body_glyph_count": excluded,
        "body_line_count": 0,
        "blank_top_pt": None,
        "blank_bottom_pt": None,
        "largest_internal_gap_pt": None,
        "internal_gaps_over_limit": [],
        "min_body_font_pt": None,
        "median_body_font_pt": None,
    }
    if not body:
        errors.append("empty_body")
    else:
        lines = _lines(body)
        first_top = min(c["top"] for c in body)
        last_bottom = max(c["bottom"] for c in body)
        top_gap, bottom_gap = first_top - top, bottom - last_bottom
        gaps = [
            {"after_bottom_pt": _rounded(a["bottom"]), "before_top_pt": _rounded(b["top"]),
             "gap_pt": _rounded(b["top"] - a["bottom"])}
            for a, b in zip(lines, lines[1:])
        ]
        excessive = [gap for gap in gaps if gap["gap_pt"] > MAX_GAP_PT + 0.0001]
        if top_gap > MAX_GAP_PT + 0.0001:
            errors.append("top_gap_exceeds_limit")
        if bottom_gap > MAX_GAP_PT + 0.0001:
            errors.append("bottom_gap_exceeds_limit")
        if excessive:
            errors.append("internal_gap_exceeds_limit")
        # Larger type is appropriate in the first-page identity block only.
        body_sizes = [
            c["size"] for c in body
            if not (page.page_number == 1 and c["bottom"] <= LIMITS["identity_bottom_pt"])
            and c["text"].strip() not in {"•", "·", "▪", "–", "-", "○"}
        ]
        if not body_sizes:
            errors.append("no_substantive_body_text")
        else:
            if min(body_sizes) < LIMITS["min_body_font_pt"] - _EPSILON:
                errors.append("body_font_too_small")
            if statistics.median(body_sizes) > LIMITS["max_median_body_font_pt"] + _EPSILON:
                errors.append("body_font_inflated")
        if any(c["size"] > LIMITS["max_identity_font_pt"] + _EPSILON for c in body):
            errors.append("font_exceeds_readable_layout_limit")
        result.update({
            "body_line_count": len(lines),
            "body_first_text_top_pt": _rounded(first_top),
            "body_last_text_bottom_pt": _rounded(last_bottom),
            "blank_top_pt": _rounded(top_gap),
            "blank_bottom_pt": _rounded(bottom_gap),
            "largest_internal_gap_pt": max((g["gap_pt"] for g in gaps), default=0.0),
            "internal_gaps_over_limit": excessive,
            "min_body_font_pt": _rounded(min(body_sizes)) if body_sizes else None,
            "median_body_font_pt": _rounded(statistics.median(body_sizes)) if body_sizes else None,
        })
    result["errors"] = list(dict.fromkeys(errors))
    return result


def measure_resume_layout(pdf_path: Path) -> dict[str, object]:
    """Read one exact PDF snapshot and return a deterministic hash-bound receipt."""
    try:
        pdfplumber = importlib.import_module("pdfplumber")
    except ImportError as exc:
        raise LayoutMeasurementError(
            "pdfplumber_unavailable: use the Codex bundled Python runtime or install career-pipeline[pdf]"
        ) from exc
    try:
        data = pdf_path.read_bytes()
        _require_supported_rendering(data)
        with pdfplumber.open(io.BytesIO(data)) as source:
            if not source.pages:
                raise LayoutMeasurementError("pdf_has_no_pages")
            pages = [_measure_page(page) for page in source.pages]
    except LayoutMeasurementError:
        raise
    except Exception as exc:
        raise LayoutMeasurementError(f"pdf_measurement_failed: {type(exc).__name__}") from exc
    errors = [f"page_{page['page_number']}_{error}" for page in pages for error in page["errors"]]
    if len(pages) != 2:
        errors.insert(0, "resume_page_count")
    return {
        "schema_version": 1,
        "policy_id": POLICY_ID,
        "pdf_sha256": hashlib.sha256(data).hexdigest(),
        "pdf_page_count": len(pages),
        "geometry": dict(GEOMETRY),
        "limits": dict(LIMITS),
        "pages": pages,
        "errors": errors,
        "passed": not errors,
    }


def validate_layout_receipt(value: object) -> tuple[str, ...]:
    """Validate required receipt identity; packet APIs also remeasure the PDF."""
    if not isinstance(value, Mapping):
        return ("resume_layout_missing",)
    if (
        value.get("schema_version") != 1
        or value.get("policy_id") != POLICY_ID
        or value.get("geometry") != GEOMETRY
        or value.get("limits") != LIMITS
        or not isinstance(value.get("pdf_sha256"), str)
        or re.fullmatch(r"[a-f0-9]{64}", value["pdf_sha256"]) is None
        or value.get("pdf_page_count") != 2
        or not isinstance(value.get("pages"), list)
        or len(value["pages"]) != 2
    ):
        return ("resume_layout_invalid",)
    if value.get("passed") is not True or value.get("errors") != []:
        return ("resume_layout_failed",)
    return ()
