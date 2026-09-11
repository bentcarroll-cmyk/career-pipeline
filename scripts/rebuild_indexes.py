#!/usr/bin/env python3
"""Rebuild disposable indexes from canonical local job folders."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.indexes import rebuild_indexes
from career_pipeline.workspace import create_workspace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    indexes = rebuild_indexes(create_workspace(args.workspace))
    print(f"indexes rebuilt for {len(indexes.backlog['jobs'])} jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
