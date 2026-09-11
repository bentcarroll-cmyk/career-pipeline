#!/usr/bin/env python3
"""Check readiness from persisted configuration and onboarding state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.onboarding import ConnectorStatus, OnboardingState
from career_pipeline.readiness import check_readiness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--onboarding", required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    raw = json.loads(args.onboarding.read_text(encoding="utf-8"))
    connectors = {
        name: ConnectorStatus(value["decision"], tuple(value.get("capabilities", ())))
        for name, value in raw.get("connectors", {}).items()
    }
    state = OnboardingState(
        stage=raw["stage"],
        completed=tuple(raw.get("completed", ())),
        connectors=connectors,
        profile_hash=raw.get("profile_hash"),
        criteria_hash=raw.get("criteria_hash"),
    )
    report = check_readiness(config, state)
    print(json.dumps({"ready": report.ready, "failure_codes": report.failure_codes}))
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
