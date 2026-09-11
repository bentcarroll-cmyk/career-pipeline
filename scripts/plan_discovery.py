#!/usr/bin/env python3
"""Partition normalized snapshots against an existing duplicate baseline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.checkpoints import stable_review_batch
from career_pipeline.dedupe import candidate_key, partition_candidates
from career_pipeline.sources.base import CandidateJob


def _load(path: Path) -> list[CandidateJob]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        CandidateJob(
            **{
                **item,
                "responsibilities": tuple(item.get("responsibilities", ())),
                "uncertainties": tuple(item.get("uncertainties", ())),
            }
        )
        for item in raw.get("jobs", [])
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--existing", required=True, type=Path)
    args = parser.parse_args()
    partition = partition_candidates(_load(args.candidates), _load(args.existing))
    keys = tuple(candidate_key(job) for job in partition.novel)
    print(
        json.dumps(
            {
                "novel_keys": keys,
                "duplicate_count": len(partition.duplicates),
                "stable_review_batch": stable_review_batch(keys),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
