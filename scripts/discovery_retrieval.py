#!/usr/bin/env python3
"""Account for source queries, raw responses, and resumable board retrieval."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline import collectors, retrieval
from career_pipeline.atomic import atomic_write_json
from career_pipeline.workspace import create_workspace


class CommandError(ValueError):
    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise CommandError("invalid_arguments: " + message)


def parser():
    command = JsonArgumentParser(description=__doc__)
    command.add_argument("--workspace", required=True, type=Path)
    command.add_argument("--occurred-at", help="Original timezone-aware event time; defaults to the current UTC clock")
    command.add_argument("--output", type=Path)
    subcommands = command.add_subparsers(dest="command", required=True)
    register = subcommands.add_parser("register")
    register.add_argument("--run-id", required=True)
    register.add_argument("--source", required=True)
    register.add_argument("--provider", required=True)
    register.add_argument("--query", type=Path, required=True)
    capture = subcommands.add_parser("capture")
    capture.add_argument("--scope-id", required=True)
    capture.add_argument("--input", type=Path, required=True)
    capture.add_argument("--cursor")
    collect = subcommands.add_parser("collect")
    collect.add_argument("--scope-id", required=True)
    subcommands.add_parser("status")
    failure = subcommands.add_parser("fail")
    failure.add_argument("--scope-id", required=True)
    failure.add_argument("--reason", required=True)
    failure.add_argument("--next-action", required=True)
    failure.add_argument("--source-record-id", help="Required when recording a failed fetch for a known missing-description pointer")
    resolve = subcommands.add_parser("resolve-pointer")
    resolve.add_argument("--scope-id", required=True)
    resolve.add_argument("--source-record-id", required=True)
    resolve.add_argument("--input", type=Path, required=True)
    return command


def event_time(value=None):
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CommandError("invalid_occurred_at") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CommandError("timezone_required")
    if parsed > datetime.now(timezone.utc):
        raise CommandError("future_occurred_at")
    return value


def load_document(path):
    return json.loads(path.read_text(encoding="utf-8"))


def collect_scope(workspace, scope_id, *, occurred_at=None):
    # Re-audit immutable evidence and finish any interrupted local intake before
    # consulting saved flags or issuing another network request.
    scope = retrieval.replay_scope(workspace, scope_id, now=event_time(occurred_at))
    if scope.get("complete"):
        return scope
    if scope["provider"] not in {"greenhouse", "ashby", "lever"}:
        result = retrieval.record_failure(
            workspace, scope_id, now=event_time(occurred_at),
            reason="provider_has_no_supported_board_collector",
            next_action="Use the registered native connector query and capture its entire response; preserve its coverage limitation.",
        )
        raise CommandError("unsupported_board_collector", result)
    while not scope.get("exhausted"):
        cursor = scope.get("next_cursor")
        try:
            response = collectors.fetch_board_page(scope["provider"], query=scope["query"], cursor=cursor)
        except (OSError, ValueError, TypeError) as exc:
            result = retrieval.record_failure(
                workspace, scope_id, now=event_time(occurred_at), reason=str(exc),
                next_action="Retry collect for this scope; it resumes at the saved continuation.",
            )
            raise CommandError("board_retrieval_failed: " + str(exc), result) from exc
        # capture_response durably saves the raw page before parsing or intake.
        # No subsequent provider request may occur until this returns.
        scope = retrieval.capture_response(
            workspace, scope_id, response, now=event_time(occurred_at), cursor=cursor,
        )
        if scope.get("capture_status") == "invalid":
            raise CommandError("invalid_provider_response", scope)
        if not scope.get("exhausted") and scope.get("next_cursor") in (None, cursor):
            result = retrieval.record_failure(
                workspace, scope_id, now=event_time(occurred_at), reason="retrieval_made_no_progress",
                next_action="Inspect the saved provider response and resolve its continuation or coverage limitation before retrying.",
            )
            raise CommandError("retrieval_incomplete", result)
    if not scope.get("complete"):
        raise CommandError("retrieval_has_unresolved_pointers", scope)
    return scope


def main(argv=None):
    args = None
    try:
        args = parser().parse_args(argv)
        now = event_time(args.occurred_at)
        workspace = create_workspace(args.workspace)
        if args.command == "register":
            result = retrieval.register_scope(
                workspace, run_id=args.run_id, source=args.source, provider=args.provider,
                query=load_document(args.query), now=now,
            )
        elif args.command == "capture":
            result = retrieval.capture_response(
                workspace, args.scope_id, load_document(args.input), now=now, cursor=args.cursor,
            )
            if result.get("capture_status") == "invalid":
                raise CommandError("invalid_provider_response", result)
        elif args.command == "collect":
            result = collect_scope(workspace, args.scope_id, occurred_at=args.occurred_at)
        elif args.command == "fail":
            target = {"source_record_id": args.source_record_id} if args.source_record_id is not None else {}
            result = retrieval.record_failure(
                workspace, args.scope_id, now=now, reason=args.reason, next_action=args.next_action, **target,
            )
        elif args.command == "resolve-pointer":
            result = retrieval.resolve_pointer(
                workspace, args.scope_id, source_record_id=args.source_record_id,
                record=load_document(args.input), now=now,
            )
        else:
            result = retrieval.summary(workspace, now=now)
        if args.output:
            atomic_write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        failure = {"error": str(exc)}
        if isinstance(exc, CommandError) and exc.result is not None:
            failure["scope"] = exc.result
            if args is not None and args.output:
                try:
                    atomic_write_json(args.output, exc.result)
                except OSError as write_error:
                    failure["output_error"] = str(write_error)
        print(json.dumps(failure, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
