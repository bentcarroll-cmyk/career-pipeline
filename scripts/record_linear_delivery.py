#!/usr/bin/env python3
"""Verify Linear readback and atomically record a delivery receipt."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.atomic import atomic_write_json
from career_pipeline.checkpoints import DiscoveryState
from career_pipeline.linear_delivery import (
    LinearIssuePayload,
    record_delivery,
    verify_issue_readback,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--actual", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    args = parser.parse_args()
    expected_raw = json.loads(args.expected.read_text(encoding="utf-8"))
    expected = LinearIssuePayload(
        **{
            **expected_raw,
            "labels": tuple(expected_raw.get("labels", ())),
        }
    )
    actual = json.loads(args.actual.read_text(encoding="utf-8"))
    raw_state = (
        json.loads(args.state.read_text(encoding="utf-8"))
        if args.state.exists()
        else {"sources": {}, "stable_review_batch": None, "deliveries": {}}
    )
    state = DiscoveryState(
        sources={},
        stable_review_batch=raw_state.get("stable_review_batch"),
        deliveries=raw_state.get("deliveries", {}),
    )
    receipt = verify_issue_readback(expected, actual)
    updated = record_delivery(state, receipt)
    atomic_write_json(
        args.state,
        {
            "schema_version": 1,
            "sources": raw_state.get("sources", {}),
            "stable_review_batch": updated.stable_review_batch,
            "deliveries": dict(updated.deliveries),
            "last_delivery_receipt": asdict(receipt),
        },
    )
    print(f"verified Linear delivery: {receipt.issue_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
