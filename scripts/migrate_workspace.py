#!/usr/bin/env python3
"""Plan or explicitly apply a backed-up workspace migration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.migrations import apply_migration, plan_migration
from career_pipeline.workspace import workspace_paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--target-version", type=int, default=2)
    parser.add_argument("--confirm")
    args = parser.parse_args()
    plan = plan_migration(
        workspace_paths(args.workspace),
        args.target_version,
    )
    if args.confirm:
        apply_migration(plan, args.confirm)
    print(
        json.dumps(
            {
                "from_version": plan.from_version,
                "target_version": plan.target_version,
                "changes": plan.changes,
                "confirmation_token": plan.confirmation_token,
                "backup_path": plan.backup_dir.relative_to(plan.workspace.root).as_posix(),
                "applied": bool(args.confirm),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
