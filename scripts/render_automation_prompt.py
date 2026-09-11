#!/usr/bin/env python3
"""Render an allowed automation prompt from non-sensitive configuration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.automation_policy import render_automation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", required=True, choices=("discovery", "lifecycle"))
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    print(render_automation(args.kind, config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
