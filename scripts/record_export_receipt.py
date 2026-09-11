#!/usr/bin/env python3
"""Verify connector readback and append an optional local export receipt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.exports import record_verified_export
from career_pipeline.linear_delivery import (
    LinearExportPayload,
    verify_linear_export_readback,
)
from career_pipeline.workspace import create_workspace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--readback", required=True, type=Path)
    parser.add_argument("--exported-at", required=True)
    parser.add_argument("--explicit-request", action="store_true")
    args = parser.parse_args()
    raw_payload = json.loads(args.payload.read_text(encoding="utf-8"))
    payload = LinearExportPayload(
        job_id=raw_payload["job_id"],
        title=raw_payload["title"],
        team_id=raw_payload["team_id"],
        project_id=raw_payload["project_id"],
        labels=tuple(raw_payload["labels"]),
        description=raw_payload["description"],
        posting_url=raw_payload["posting_url"],
        application_url=raw_payload["application_url"],
    )
    receipt = verify_linear_export_readback(
        payload,
        json.loads(args.readback.read_text(encoding="utf-8")),
        exported_at=args.exported_at,
    )
    record_verified_export(
        create_workspace(args.workspace),
        payload.job_id,
        receipt,
        explicit_request=args.explicit_request,
    )
    print(f"optional export verified for {payload.job_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
