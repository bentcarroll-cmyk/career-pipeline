#!/usr/bin/env python3
"""Create one canonical local job from reviewed JSON and Markdown evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.evaluation import EvidenceClaim, JobAssessment
from career_pipeline.job_store import create_job
from career_pipeline.sources.base import CandidateJob
from career_pipeline.workspace import create_workspace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--assessment", required=True, type=Path)
    parser.add_argument("--posting", required=True, type=Path)
    parser.add_argument("--assessment-markdown", required=True, type=Path)
    parser.add_argument("--occurred-at", required=True)
    args = parser.parse_args()
    candidate_raw = json.loads(args.candidate.read_text(encoding="utf-8"))
    candidate_raw["responsibilities"] = tuple(candidate_raw["responsibilities"])
    candidate_raw["uncertainties"] = tuple(candidate_raw.get("uncertainties", ()))
    assessment_raw = json.loads(args.assessment.read_text(encoding="utf-8"))
    assessment = JobAssessment(
        disposition=assessment_raw["disposition"],
        role_to_profile_fit=assessment_raw["role_to_profile_fit"],
        strengths=tuple(EvidenceClaim(**value) for value in assessment_raw["strengths"]),
        gaps=tuple(assessment_raw.get("gaps", ())),
        uncertainties=tuple(assessment_raw.get("uncertainties", ())),
    )
    record = create_job(
        create_workspace(args.workspace),
        CandidateJob(**candidate_raw),
        assessment,
        posting_markdown=args.posting.read_text(encoding="utf-8"),
        assessment_markdown=args.assessment_markdown.read_text(encoding="utf-8"),
        occurred_at=args.occurred_at,
    )
    print(record["job_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
