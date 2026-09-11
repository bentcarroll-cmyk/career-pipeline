#!/usr/bin/env python3
"""Advance one packet stage with a durable receipt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.packets import advance_packet, load_manifest, save_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--ticket-id", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    updated = advance_packet(manifest, args.ticket_id, args.stage, receipt)
    save_manifest(args.manifest, updated)
    print(f"{args.ticket_id} advanced to {args.stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
