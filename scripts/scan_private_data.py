#!/usr/bin/env python3
"""Scan a repository tree or plugin archive for private material."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.privacy import scan_tree


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) == 2 else ROOT
    findings = scan_tree(target)
    for finding in findings:
        location = f"{finding.path}:{finding.line}" if finding.line else finding.path
        print(f"{location}: {finding.rule}")
    if findings:
        return 1
    print("privacy scan passed: 0 findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
