#!/usr/bin/env python3
"""Create or preview the standard Career Pipeline workspace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.workspace import _DIRECTORIES, create_workspace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        for relative in _DIRECTORIES:
            print(relative)
        return 0
    create_workspace(args.root, ROOT)
    print("workspace created and verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
