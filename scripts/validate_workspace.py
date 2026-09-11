#!/usr/bin/env python3
"""Validate a Career Pipeline workspace without displaying user content."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.workspace import _DIRECTORIES


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    missing = [
        relative for relative in _DIRECTORIES if not (args.root / relative).is_dir()
    ]
    for relative in missing:
        print(f"missing: {relative}")
    if missing:
        return 1
    print("workspace validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
