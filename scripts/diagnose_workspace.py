#!/usr/bin/env python3
"""Report content-free repair codes for persisted Career Pipeline state."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.schema import diagnose_workspace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    findings = diagnose_workspace(args.root)
    for schema_name, code in findings:
        print(f"{schema_name}.{code}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
