"""Validate that semantic job assessments remain evidence-backed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .contracts import ValidationError
from .sources.base import CandidateJob


@dataclass(frozen=True)
class EvidenceClaim:
    profile_evidence_id: str
    claim: str


@dataclass(frozen=True)
class JobAssessment:
    disposition: str
    role_to_profile_fit: str
    strengths: tuple[EvidenceClaim, ...]
    gaps: tuple[str, ...]
    uncertainties: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()


def validate_assessment(
    job: CandidateJob,
    profile: Mapping[str, object],
    assessment: JobAssessment,
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if assessment.disposition not in {
        "strong_match",
        "worth_considering",
        "non_match",
    }:
        errors.append(
            ValidationError("invalid_disposition", "disposition", "unsupported value")
        )
    if not assessment.role_to_profile_fit.strip():
        errors.append(
            ValidationError("required_string", "role_to_profile_fit", "must be set")
        )
    if not job.responsibilities:
        errors.append(
            ValidationError(
                "responsibilities_missing",
                "job.responsibilities",
                "responsibilities must be verified before assessment",
            )
        )
    evidence = profile.get("evidence", {})
    evidence = evidence if isinstance(evidence, Mapping) else {}
    for index, strength in enumerate(assessment.strengths):
        if (
            not strength.claim.strip()
            or strength.profile_evidence_id not in evidence
        ):
            errors.append(
                ValidationError(
                    "unsupported_strength",
                    f"strengths.{index}",
                    "positive claims must reference approved profile evidence",
                )
            )
    if (
        assessment.disposition in {"strong_match", "worth_considering"}
        and not assessment.strengths
    ):
        errors.append(
            ValidationError(
                "strengths_required",
                "strengths",
                "qualifying assessments need evidence-supported strengths",
            )
        )
    return errors
