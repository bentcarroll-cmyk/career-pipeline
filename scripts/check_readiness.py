#!/usr/bin/env python3
"""Check readiness from persisted configuration and onboarding state."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.onboarding import ConnectorStatus, OnboardingState
from career_pipeline.readiness import check_readiness
from career_pipeline.workspace import create_workspace


def _state_from_raw(raw: dict[str, object]) -> OnboardingState:
    connectors = {
        name: ConnectorStatus(value["decision"], tuple(value.get("capabilities", ())))
        for name, value in raw.get("connectors", {}).items()
    }
    return OnboardingState(
        stage=raw["stage"],
        completed=tuple(raw.get("completed", ())),
        connectors=connectors,
        receipts=raw.get("receipts", {}),
        profile_hash=raw.get("profile_hash"),
        criteria_hash=raw.get("criteria_hash"),
    )


def _run_fixture(
    path: Path,
) -> tuple[dict[str, object], OnboardingState, tempfile.TemporaryDirectory]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    config = fixture["config"]
    raw_state = fixture["onboarding"]
    temp = tempfile.TemporaryDirectory()
    paths = create_workspace(Path(temp.name) / "Synthetic-Career")
    profile = paths.profile / "Career_Profile.md"
    criteria = paths.profile / "Search_Criteria.md"
    profile.write_text("Synthetic approved profile\n", encoding="utf-8")
    criteria.write_text("Synthetic approved criteria\n", encoding="utf-8")
    (paths.profile / "Writing_Preferences.md").write_text(
        "Synthetic writing preferences\n", encoding="utf-8"
    )
    (paths.sources / "Resume_Original.txt").write_text(
        "Synthetic source resume\n", encoding="utf-8"
    )
    config["workspace_root"] = str(paths.root)
    raw_state["profile_hash"] = hashlib.sha256(profile.read_bytes()).hexdigest()
    raw_state["criteria_hash"] = hashlib.sha256(criteria.read_bytes()).hexdigest()
    state = _state_from_raw(raw_state)
    return config, state, temp


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    parser.add_argument("--onboarding", type=Path)
    parser.add_argument("--fixture", type=Path)
    args = parser.parse_args()
    fixture_temp = None
    if args.fixture:
        config, state, fixture_temp = _run_fixture(args.fixture)
    elif args.config and args.onboarding:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        state = _state_from_raw(
            json.loads(args.onboarding.read_text(encoding="utf-8"))
        )
    else:
        parser.error("use --fixture or both --config and --onboarding")
    report = check_readiness(config, state)
    print(json.dumps({"ready": report.ready, "failure_codes": report.failure_codes}))
    if fixture_temp is not None:
        fixture_temp.cleanup()
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
