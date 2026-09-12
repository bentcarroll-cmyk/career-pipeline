"""Validate that semantic job assessments remain evidence-backed."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Mapping

from .contracts import ValidationError, WorkspacePaths
from .onboarding import load_onboarding_state
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
    profile_hash: str | None = None
    criteria_hash: str | None = None


@dataclass(frozen=True)
class ApprovedAssessmentInputs:
    profile: Mapping[str, object]
    profile_hash: str
    criteria_hash: str


class AssessmentApprovalError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


_EVIDENCE_ID = re.compile(r"\bEV-[A-Za-z0-9][A-Za-z0-9_-]*\b")
_SHA256 = re.compile(r"[a-f0-9]{64}")


def load_approved_assessment_inputs(
    workspace: WorkspacePaths,
) -> ApprovedAssessmentInputs:
    profile_path = workspace.profile / "Career_Profile.md"
    criteria_path = workspace.profile / "Search_Criteria.md"
    onboarding_path = workspace.state / "onboarding-state.json"
    if (
        profile_path.is_symlink()
        or criteria_path.is_symlink()
        or onboarding_path.is_symlink()
        or not profile_path.is_file()
        or not criteria_path.is_file()
        or not onboarding_path.is_file()
    ):
        raise AssessmentApprovalError("approved_assessment_inputs_missing")
    try:
        profile_bytes = profile_path.read_bytes()
        criteria_bytes = criteria_path.read_bytes()
        onboarding = load_onboarding_state(onboarding_path)
        profile_text = profile_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise AssessmentApprovalError("approved_assessment_inputs_invalid") from exc
    profile_hash = hashlib.sha256(profile_bytes).hexdigest()
    criteria_hash = hashlib.sha256(criteria_bytes).hexdigest()
    if (
        _SHA256.fullmatch(onboarding.profile_hash or "") is None
        or onboarding.profile_hash != profile_hash
    ):
        raise AssessmentApprovalError("profile_approval_stale")
    if (
        _SHA256.fullmatch(onboarding.criteria_hash or "") is None
        or onboarding.criteria_hash != criteria_hash
    ):
        raise AssessmentApprovalError("criteria_approval_stale")
    evidence_ids = tuple(dict.fromkeys(_EVIDENCE_ID.findall(profile_text)))
    return ApprovedAssessmentInputs(
        profile={"evidence": {evidence_id: True for evidence_id in evidence_ids}},
        profile_hash=profile_hash,
        criteria_hash=criteria_hash,
    )


def validate_assessment_bindings(
    assessment: JobAssessment,
    approved: ApprovedAssessmentInputs,
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if assessment.profile_hash != approved.profile_hash:
        errors.append(
            ValidationError("stale_profile_hash", "profile_hash", "must match current approval")
        )
    if assessment.criteria_hash != approved.criteria_hash:
        errors.append(
            ValidationError("stale_criteria_hash", "criteria_hash", "must match current approval")
        )
    return errors


def assessment_content_hash(assessment: JobAssessment) -> str:
    payload = json.dumps(
        asdict(assessment),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
