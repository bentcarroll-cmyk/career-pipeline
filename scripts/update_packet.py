#!/usr/bin/env python3
"""Advance one packet stage with a durable receipt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.packets import (
    advance_packet,
    complete_local_delivery,
    load_manifest,
    persist_manifest,
)
from career_pipeline.workspace import create_workspace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument(
        "--stage",
        required=True,
        choices=(
            "posting_verified",
            "drafted",
            "quality_checked",
            "saved",
            "complete-local",
        ),
    )
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--occurred-at")
    args = parser.parse_args()
    workspace = create_workspace(args.workspace)
    manifest_path = workspace.state / "application-manifest.json"
    manifest = load_manifest(manifest_path)
    if args.stage == "complete-local":
        if not args.occurred_at:
            parser.error("--occurred-at is required for complete-local")
        updated = complete_local_delivery(
            workspace,
            manifest,
            args.job_id,
            occurred_at=args.occurred_at,
        )
    else:
        if args.receipt is None:
            parser.error("--receipt is required for this stage")
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        updated = advance_packet(manifest, args.job_id, args.stage, receipt)
        updated = persist_manifest(workspace, updated)
    print(f"{args.job_id} advanced to {updated.packets[args.job_id][-1].stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
