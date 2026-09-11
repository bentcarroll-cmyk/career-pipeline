#!/usr/bin/env python3
"""Update one canonical local job status and append its event."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.job_store import update_job_status
from career_pipeline.workspace import create_workspace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--occurred-at", required=True)
    args = parser.parse_args()
    record = update_job_status(
        create_workspace(args.workspace),
        args.job_id,
        args.status,
        occurred_at=args.occurred_at,
    )
    print(f"{record['job_id']} {record['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
