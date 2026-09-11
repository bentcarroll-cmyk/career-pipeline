#!/usr/bin/env python3
"""Build a deterministic Linear issue payload from reviewed JSON."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.atomic import atomic_write_json
from career_pipeline.evaluation import EvidenceClaim, JobAssessment
from career_pipeline.linear_delivery import build_issue_payload
from career_pipeline.sources.base import CandidateJob


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--assessment", required=True, type=Path)
    parser.add_argument("--linear", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raw_job = json.loads(args.job.read_text(encoding="utf-8"))
    job = CandidateJob(
        **{
            **raw_job,
            "responsibilities": tuple(raw_job.get("responsibilities", ())),
            "uncertainties": tuple(raw_job.get("uncertainties", ())),
        }
    )
    raw_assessment = json.loads(args.assessment.read_text(encoding="utf-8"))
    assessment = JobAssessment(
        disposition=raw_assessment["disposition"],
        role_to_profile_fit=raw_assessment["role_to_profile_fit"],
        strengths=tuple(
            EvidenceClaim(item["profile_evidence_id"], item["claim"])
            for item in raw_assessment.get("strengths", ())
        ),
        gaps=tuple(raw_assessment.get("gaps", ())),
        uncertainties=tuple(raw_assessment.get("uncertainties", ())),
    )
    config = json.loads(args.linear.read_text(encoding="utf-8"))
    atomic_write_json(args.output, asdict(build_issue_payload(job, assessment, config)))
    print("Linear issue payload built")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
