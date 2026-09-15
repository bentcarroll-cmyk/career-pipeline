#!/usr/bin/env python3
"""Persist complete source intake and resume explicit candidate reviews."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline import review_queue
from career_pipeline.atomic import atomic_write_json
from career_pipeline.workspace import create_workspace


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--occurred-at", required=True)
    parser.add_argument("--output", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    intake = commands.add_parser("ingest")
    intake.add_argument("--input", required=True, type=Path)
    intake.add_argument("--source", help="Required to record an actually empty source result")
    pending = commands.add_parser("next")
    pending.add_argument("--limit", type=int)
    commands.add_parser("status")
    decide = commands.add_parser("decide")
    decide.add_argument("--input", required=True, type=Path)
    recovery_plan = commands.add_parser("plan-recovery", help="Preview mixed posting IDs without changing the queue")
    recovery_plan.add_argument("--review-id", action="append", dest="review_ids")
    recover = commands.add_parser("recover", help="Apply an exact bounded recovery plan")
    recover.add_argument("--input", required=True, type=Path)
    prefilter = commands.add_parser("prefilter", help="Apply approved geographic exclusions to pending intact snapshots")
    prefilter.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    workspace = create_workspace(args.workspace)
    try:
        if args.command == "ingest":
            records = json.loads(args.input.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                raise ValueError("intake_must_be_array")
            review_queue.ingest(workspace, records, now=args.occurred_at, source=args.source)
        elif args.command == "decide":
            decisions = json.loads(args.input.read_text(encoding="utf-8"))
            for value in decisions if isinstance(decisions, list) else [decisions]:
                review_queue.record_decision(workspace, value["review_id"], value["decision"],
                    expected_revision=value["expected_revision"], expected_context=value["expected_context"], now=args.occurred_at)
        if args.command == "plan-recovery":
            result = review_queue.plan_posting_identity_recovery(workspace, review_ids=args.review_ids)
        elif args.command == "recover":
            plan = json.loads(args.input.read_text(encoding="utf-8"))
            result = review_queue.recover_posting_identities(workspace, review_ids=plan["review_ids"],
                expected_queue_hash=plan["expected_queue_hash"], now=args.occurred_at)
        elif args.command == "prefilter":
            result = review_queue.apply_location_prefilter(workspace, now=args.occurred_at, dry_run=args.dry_run)
        else:
            result = review_queue.summary(workspace, now=args.occurred_at)
        if args.command == "next":
            if args.limit is not None and args.limit < 1:
                raise ValueError("positive_limit_required")
            result = {"summary": result, "items": review_queue.next_items(workspace, now=args.occurred_at, limit=args.limit)}
        if args.output:
            atomic_write_json(args.output, result)
            print(json.dumps({"output": str(args.output)}))
        else:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
