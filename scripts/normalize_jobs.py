#!/usr/bin/env python3
"""Normalize a saved source snapshot without performing network access."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.atomic import atomic_write_json
from career_pipeline.sources import ashby, generic, greenhouse, lever
from career_pipeline.sources.base import SourceSnapshot


ADAPTERS = {
    "ashby": ashby.normalize,
    "greenhouse": greenhouse.normalize,
    "lever": lever.normalize,
    "generic": generic.normalize,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", required=True, choices=tuple(ADAPTERS))
    parser.add_argument("--source", required=True)
    parser.add_argument("--fetched-at", required=True)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--employer")
    parser.add_argument("--board")
    args = parser.parse_args()
    records = json.loads(args.input.read_text(encoding="utf-8"))
    snapshot = SourceSnapshot(
        args.source,
        args.fetched_at,
        records,
        employer=args.employer,
        board=args.board,
    )
    jobs = ADAPTERS[args.adapter](snapshot)
    atomic_write_json(args.output, {"jobs": [asdict(job) for job in jobs]})
    print(f"normalized {len(jobs)} job record(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
