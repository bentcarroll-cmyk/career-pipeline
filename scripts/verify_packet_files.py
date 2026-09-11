#!/usr/bin/env python3
"""Verify final packet PDFs without printing their contents."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.packets import load_manifest, verify_local_artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--ticket-id", required=True)
    args = parser.parse_args()
    record = load_manifest(args.manifest).packets[args.ticket_id][-1]
    verification = verify_local_artifacts(record)
    print(json.dumps({
        "valid": verification.valid,
        "errors": verification.errors,
        "hashes": dict(verification.hashes),
    }, sort_keys=True))
    return 0 if verification.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
