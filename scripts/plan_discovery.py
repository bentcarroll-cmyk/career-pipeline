#!/usr/bin/env python3
"""Persist reviewed synthetic-safe discovery input to the local job store."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.checkpoints import (
    DiscoveryState,
    SourceResult,
    load_discovery_state,
    merge_discovery_state,
)
from career_pipeline.discovery import ReviewedJob, deliver_reviewed_jobs
from career_pipeline.evaluation import EvidenceClaim, JobAssessment
from career_pipeline.sources.base import CandidateJob
from career_pipeline.workspace import create_workspace


def _reviewed(path: Path) -> tuple[ReviewedJob, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    results: list[ReviewedJob] = []
    for item in raw.get("reviewed", ()):
        candidate_raw = item["candidate"]
        assessment_raw = item["assessment"]
        candidate = CandidateJob(
            **{
                **candidate_raw,
                "responsibilities": tuple(candidate_raw.get("responsibilities", ())),
                "uncertainties": tuple(candidate_raw.get("uncertainties", ())),
            }
        )
        assessment = JobAssessment(
            disposition=assessment_raw["disposition"],
            role_to_profile_fit=assessment_raw["role_to_profile_fit"],
            strengths=tuple(
                EvidenceClaim(**claim) for claim in assessment_raw.get("strengths", ())
            ),
            gaps=tuple(assessment_raw.get("gaps", ())),
            uncertainties=tuple(assessment_raw.get("uncertainties", ())),
        )
        results.append(
            ReviewedJob(
                candidate,
                assessment,
                item["posting_markdown"],
                item["assessment_markdown"],
            )
        )
    return tuple(results)


def _source_results(path: Path) -> tuple[tuple[str, SourceResult], ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    results: list[tuple[str, SourceResult]] = []
    for source, value in sorted(raw.get("source_results", {}).items()):
        results.append(
            (
                source,
                SourceResult(
                    success=value["success"],
                    completed_at=value["completed_at"],
                    seen_records=tuple(value.get("seen_records", ())),
                    cursor=value.get("cursor"),
                ),
            )
        )
    return tuple(results)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--reviewed", required=True, type=Path)
    parser.add_argument("--occurred-at", required=True)
    args = parser.parse_args()
    workspace = create_workspace(args.workspace)
    state_path = workspace.state / "discovery-state.json"
    state = load_discovery_state(state_path) if state_path.exists() else DiscoveryState()
    outcome = deliver_reviewed_jobs(
        workspace,
        state,
        _reviewed(args.reviewed),
        occurred_at=args.occurred_at,
    )
    state = merge_discovery_state(
        workspace,
        outcome.state,
        _source_results(args.reviewed),
    )
    print(
        json.dumps(
            {
                "created_job_ids": outcome.created_job_ids,
                "duplicate_keys": outcome.duplicate_keys,
                "non_match_keys": outcome.non_match_keys,
                "meaningful_change_job_ids": outcome.meaningful_change_job_ids,
                "stable_review_batch": state.stable_review_batch,
                "run_evidence": outcome.run_evidence.relative_to(workspace.root).as_posix(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
