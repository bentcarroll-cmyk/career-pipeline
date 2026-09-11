#!/usr/bin/env python3
"""Build the deterministic Career Pipeline private-beta archive."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.packaging import build_plugin_archive


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    result = build_plugin_archive(ROOT, args.output)
    print(
        json.dumps(
            {
                "archive": str(result.archive),
                "checksum": str(result.checksum),
                "sha256": result.sha256,
                "member_count": len(result.members),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
