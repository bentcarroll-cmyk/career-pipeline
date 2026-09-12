#!/usr/bin/env python3
"""Build and render the deterministic actionable backlog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.backlog import build_actionable_backlog, render_actionable_backlog
from career_pipeline.workspace import workspace_paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    view = build_actionable_backlog(
        workspace_paths(args.workspace),
        as_of=args.as_of,
    )
    if args.json:
        print(json.dumps(view, sort_keys=True))
    else:
        print(render_actionable_backlog(view))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
