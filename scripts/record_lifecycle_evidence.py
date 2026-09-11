#!/usr/bin/env python3
"""Reconcile lifecycle evidence into canonical local status and a minimal receipt."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.reconciliation import (
    LifecycleEvidence,
    reconcile_lifecycle_evidence,
)
from career_pipeline.workspace import create_workspace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument(
        "--enabled-source",
        required=True,
        action="append",
        choices=("gmail", "google-calendar"),
    )
    args = parser.parse_args()
    evidence = LifecycleEvidence(
        **json.loads(args.evidence.read_text(encoding="utf-8"))
    )
    result = reconcile_lifecycle_evidence(
        create_workspace(args.workspace),
        evidence,
        enabled_sources=tuple(args.enabled_source),
    )
    output = asdict(result.decision)
    output["receipt_path"] = (
        result.receipt_path.relative_to(args.workspace.resolve()).as_posix()
        if result.receipt_path is not None
        else None
    )
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
