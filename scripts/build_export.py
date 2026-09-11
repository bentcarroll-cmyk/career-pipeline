#!/usr/bin/env python3
"""Build an explicit optional connector export from a canonical local job."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.atomic import atomic_write_json
from career_pipeline.linear_delivery import build_linear_export_payload
from career_pipeline.workspace import create_workspace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--destination", required=True, choices=("linear",))
    parser.add_argument("--destination-config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--explicit-request", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.destination_config.read_text(encoding="utf-8"))
    payload = build_linear_export_payload(
        create_workspace(args.workspace),
        args.job_id,
        config,
        explicit_request=args.explicit_request,
    )
    atomic_write_json(
        args.output,
        {
            "job_id": payload.job_id,
            "title": payload.title,
            "team_id": payload.team_id,
            "project_id": payload.project_id,
            "labels": list(payload.labels),
            "description": payload.description,
            "posting_url": payload.posting_url,
            "application_url": payload.application_url,
            "content_hash": payload.content_hash,
        },
    )
    print(f"optional export payload built for {payload.job_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
