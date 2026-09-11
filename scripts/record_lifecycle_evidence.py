#!/usr/bin/env python3
"""Classify lifecycle evidence and write only a minimal receipt."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.atomic import atomic_write_json
from career_pipeline.reconciliation import (
    LifecycleCandidate,
    LifecycleEvidence,
    classify_lifecycle_evidence,
    minimal_receipt,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seen", type=Path)
    args = parser.parse_args()
    evidence = LifecycleEvidence(
        **json.loads(args.evidence.read_text(encoding="utf-8"))
    )
    candidates = tuple(
        LifecycleCandidate(**item)
        for item in json.loads(args.candidates.read_text(encoding="utf-8"))
    )
    seen = (
        tuple(json.loads(args.seen.read_text(encoding="utf-8")))
        if args.seen
        else ()
    )
    decision = classify_lifecycle_evidence(evidence, candidates, seen)
    atomic_write_json(args.output, minimal_receipt(evidence, decision))
    print(json.dumps(asdict(decision), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
