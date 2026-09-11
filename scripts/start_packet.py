#!/usr/bin/env python3
"""Start or resume one packet for an explicit canonical local job request."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.packets import (
    ApplicationManifest,
    PacketOptions,
    load_manifest,
    start_packet,
)
from career_pipeline.workspace import create_workspace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--occurred-at", required=True)
    parser.add_argument("--explicit-request", action="store_true")
    parser.add_argument("--no-cover-letter", action="store_true")
    args = parser.parse_args()
    workspace = create_workspace(args.workspace)
    manifest_path = workspace.state / "application-manifest.json"
    manifest = (
        load_manifest(manifest_path)
        if manifest_path.exists()
        else ApplicationManifest()
    )
    manifest, record = start_packet(
        workspace,
        args.job_id,
        PacketOptions(cover_letter_enabled=not args.no_cover_letter),
        manifest,
        occurred_at=args.occurred_at,
        explicit_request=args.explicit_request,
    )
    print(f"{record.job_id} {record.version} {record.stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
