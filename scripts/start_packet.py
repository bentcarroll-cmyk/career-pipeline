#!/usr/bin/env python3
"""Start or resume one packet record from a synthetic-safe ticket JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.contracts import WorkspacePaths
from career_pipeline.packets import (
    ApplicationManifest,
    PacketOptions,
    PacketTicket,
    load_manifest,
    save_manifest,
    start_packet,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--ticket", required=True, type=Path)
    parser.add_argument("--no-cover-letter", action="store_true")
    args = parser.parse_args()
    workspace_root = args.workspace.resolve()
    workspace = WorkspacePaths(
        workspace_root,
        workspace_root / "Profile",
        workspace_root / "Sources",
        workspace_root / "Applications",
        workspace_root / "Runs",
        workspace_root / "State",
    )
    manifest_path = workspace.state / "application-manifest.json"
    manifest = (
        load_manifest(manifest_path)
        if manifest_path.exists()
        else ApplicationManifest()
    )
    ticket = PacketTicket(**json.loads(args.ticket.read_text(encoding="utf-8")))
    manifest, record = start_packet(
        ticket,
        workspace,
        PacketOptions(cover_letter_enabled=not args.no_cover_letter),
        manifest,
    )
    save_manifest(manifest_path, manifest)
    print(f"{record.ticket_id} {record.version} {record.stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
