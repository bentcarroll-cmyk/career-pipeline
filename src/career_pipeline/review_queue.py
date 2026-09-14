"""Durable discovery intake, explicit review outcomes, and resumable delivery.

This ledger tracks work, not canonical job identity. Employer/title hints must
be verified by a reviewer; they never suppress a listing or allocate a JOB.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from typing import Any

from .atomic import atomic_write_json
from .contracts import WorkspacePaths
from .dedupe import _normalize
from .job_store import workspace_lock_if_needed as workspace_lock

_FILE = "discovery-review-queue.json"
_STATUSES = {"unreviewed", "blocked", "qualifying", "duplicate", "excluded", "non_match"}
_BLOCKERS = {"source_unavailable", "posting_identity_ambiguous", "location_conflict",
             "application_route_unavailable", "history_unavailable"}
_RESULTS = {"http_403", "http_404", "content_missing", "conflicting_evidence",
            "identity_unresolved", "history_unavailable", "request_error"}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def _time(value: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError()
        return stamp
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("timezone_aware_timestamp_required") from exc


def _url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("https://", "http://"))


def review_context(workspace: WorkspacePaths) -> str:
    files = (workspace.profile / "Career_Profile.md", workspace.profile / "Search_Criteria.md",
             workspace.profile / "Search_Criteria.json", workspace.state / "search-criteria-approval.json")
    return _digest([hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None for p in files])


def load_queue(workspace: WorkspacePaths) -> dict:
    path = workspace.state / _FILE
    if not path.exists():
        return {"schema_version": 1, "items": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or not isinstance(value.get("items"), dict):
        raise ValueError("invalid_review_queue")
    for key, row in value["items"].items():
        if (not re.fullmatch(r"review:[a-f0-9]{64}", key) or row.get("review_id") != key
                or row.get("status") not in _STATUSES or not isinstance(row.get("revision"), int)
                or not row.get("observations")):
            raise ValueError("invalid_review_queue_item")
    return value


def enabled(workspace: WorkspacePaths) -> bool:
    config = workspace.state / "config.json"
    return (workspace.state / _FILE).exists() or (config.is_file() and
        json.loads(config.read_text()).get("require_review_queue") is True)


def _effective_status(row: dict, approval: str) -> str:
    if row.get("decision") and row.get("approval_fingerprint") != approval:
        return "unreviewed"
    return row["status"]


def _intake(raw: dict) -> dict:
    needed = ("source", "source_record_id", "employer", "title", "posting_url")
    if any(not isinstance(raw.get(k), str) or not raw[k].strip() for k in needed):
        raise ValueError("incomplete_review_intake")
    if not _url(raw["posting_url"]) or not isinstance(raw.get("raw"), dict):
        raise ValueError("source_snapshot_required")
    description = raw["raw"].get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("source_description_required")
    row = {k: raw[k] for k in needed}
    row.update(location=raw.get("location") or "", requisition_id=raw.get("requisition_id"), raw=raw["raw"])
    if not isinstance(row["location"], str) or (row["requisition_id"] is not None and not isinstance(row["requisition_id"], str)):
        raise ValueError("invalid_intake_identity")
    field_hash = raw.get("raw_field_hash") or _digest(raw["raw"])
    if not isinstance(field_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", field_hash):
        raise ValueError("invalid_source_field_hash")
    row["raw_field_hash"] = field_hash
    return row


def ingest(workspace: WorkspacePaths, records: list[dict], *, now: str, source: str | None = None) -> dict:
    """Save all returned records before choosing which are worth pursuing."""
    _time(now)
    prepared = [_intake(r) for r in records]  # Validate the whole batch before writing.
    if source is not None and (not source.strip() or any(r["source"] != source for r in prepared)):
        raise ValueError("intake_source_mismatch")
    with workspace_lock(workspace):
        queue = load_queue(workspace)
        for name in ({r["source"] for r in prepared} | ({source} if source else set())):
            queue.setdefault("intakes", {})[name] = dict(captured_at=now, returned_records=sum(r["source"] == name for r in prepared))
            receipt = dict(source=name, captured_at=now, source_record_ids=sorted({r["source_record_id"] for r in prepared if r["source"] == name}),
                           snapshot_hashes=sorted({_digest(r) for r in prepared if r["source"] == name}))
            queue.setdefault("intake_batches", {})[_digest(receipt)] = receipt
        for raw in prepared:
            identity = [_normalize(raw[k]) for k in ("source", "employer", "title", "location", "requisition_id")]
            if not raw["requisition_id"]:
                identity.append(raw["source_record_id"])
            key = "review:" + _digest(identity)
            # Accept an existing intake of this exact source ID, including queues
            # created before requisition-less IDs were part of the grouping key.
            existing = [r for r in queue["items"].values() if all(_normalize(r[k]) == _normalize(raw[k])
                        for k in ("source", "employer", "title", "location", "requisition_id")) and
                        any(o["source_record_id"] == raw["source_record_id"] for o in r["observations"])]
            if len(existing) == 1:
                key = existing[0]["review_id"]
            material = {k: v for k, v in raw["raw"].items()
                        if k not in {"jrtk", "url", "posted_date", "sponsored", "company_rating", "advertiser_name"}}
            content_hash = _digest(material)
            snapshot_hash = _digest(raw)
            snapshot = workspace.sources / "discovery-review" / f"{snapshot_hash}.json"
            if not snapshot.resolve().is_relative_to(workspace.sources.resolve()):
                raise ValueError("snapshot_outside_workspace")
            if snapshot.exists():
                if _digest(json.loads(snapshot.read_text())) != snapshot_hash:
                    raise ValueError("snapshot_hash_mismatch")
            else:
                atomic_write_json(snapshot, raw)
            observation = dict(source_record_id=raw["source_record_id"], raw_field_hash=raw["raw_field_hash"],
                               snapshot=snapshot.relative_to(workspace.root).as_posix(), snapshot_hash=snapshot_hash,
                               content_hash=content_hash, captured_at=now)
            row = queue["items"].get(key)
            if row is None:
                row = {k: raw[k] for k in ("source", "employer", "title", "location", "requisition_id", "posting_url")}
                row.update(review_id=key, revision=1, status="unreviewed", first_seen_at=now,
                           content_hash=content_hash, observations=[], history=[], decision=None)
                queue["items"][key] = row
            elif row["content_hash"] != content_hash:
                row["history"].append({k: row.get(k) for k in ("revision", "decision", "content_hash", "job_id", "approval_fingerprint")})
                row.update(revision=row["revision"] + 1, content_hash=content_hash,
                           status="unreviewed", decision=None)
                row.pop("job_id", None)
            if not any(x["snapshot_hash"] == snapshot_hash for x in row["observations"]):
                row["observations"].append(observation)
            row["last_seen_at"] = now
        atomic_write_json(workspace.state / _FILE, queue)
        return queue


def possible_existing_jobs(workspace: WorkspacePaths, row: dict) -> list[str]:
    """Offer employer/title matches as hints even when aggregator IDs differ."""
    matches = []
    for path in sorted(workspace.jobs.glob("*/job.json")):
        job = json.loads(path.read_text())
        employer, existing = _normalize(row["employer"]), _normalize(job.get("employer"))
        if (employer and existing and (employer == existing or employer in existing or existing in employer)
                and _normalize(row["title"]) == _normalize(job.get("title"))):
            matches.append(job["job_id"])
    return matches


def record_decision(workspace: WorkspacePaths, review_id: str, decision: dict,
                    *, expected_revision: int, expected_context: str, now: str) -> dict:
    """Resolve actual work, or record a specific observed blocker with a retry."""
    current_time = _time(now)
    status = decision.get("status")
    if status not in _STATUSES - {"unreviewed"}:
        raise ValueError("explicit_review_outcome_required")
    if (not isinstance(decision.get("rationale"), str) or len(decision["rationale"].strip()) < 20
            or not isinstance(decision.get("evidence"), list) or not decision["evidence"]
            or not all(_url(x) for x in decision["evidence"])):
        raise ValueError("review_rationale_and_evidence_required")
    if status == "blocked":
        attempts = decision.get("attempts")
        if (decision.get("reason_code") not in _BLOCKERS or not isinstance(attempts, list) or not attempts
                or not isinstance(decision.get("next_action"), str) or len(decision["next_action"].strip()) < 20):
            raise ValueError("specific_blocker_attempt_and_retry_required")
        for attempt in attempts:
            if not _url(attempt.get("url")) or attempt.get("result") not in _RESULTS or _time(attempt.get("checked_at")) > current_time:
                raise ValueError("invalid_blocker_attempt")
        if _time(decision.get("retry_after")) <= current_time:
            raise ValueError("future_retry_required")
    if status == "duplicate" and (not decision.get("existing_reference") or len(decision.get("identity_resolution", "")) < 20):
        raise ValueError("duplicate_reference_required")
    with workspace_lock(workspace):
        if expected_context != review_context(workspace):
            raise ValueError("stale_review_context")
        queue = load_queue(workspace)
        row = queue["items"].get(review_id)
        if row is None or row["revision"] != expected_revision:
            raise ValueError("stale_review_revision")
        if status == "qualifying" and possible_existing_jobs(workspace, row) and len(decision.get("identity_resolution", "")) < 20:
            raise ValueError("identity_resolution_required")
        row["history"].append({k: row.get(k) for k in ("revision", "decision", "approval_fingerprint", "job_id")})
        row.pop("job_id", None)
        row.update(status=status, decision=decision, reviewed_at=now, revision=row["revision"] + 1,
                   approval_fingerprint=review_context(workspace))
        atomic_write_json(workspace.state / _FILE, queue)
        return row


def summary(workspace: WorkspacePaths, *, now: str) -> dict:
    current_time = _time(now)
    queue = load_queue(workspace)
    rows = list(queue["items"].values())
    approval = review_context(workspace)
    counts = Counter(_effective_status(row, approval) for row in rows)
    due = sum(_effective_status(row, approval) == "blocked" and
              _time(row["decision"]["retry_after"]) <= current_time for row in rows)
    ready = sum(_effective_status(row, approval) == "qualifying" and not row.get("job_id") for row in rows)
    return {"total": len(rows), **{status: counts[status] for status in sorted(_STATUSES)},
            "intake_batches": {key: {"source": batch["source"], "captured_at": batch["captured_at"],
                "returned_records": len(batch["source_record_ids"])} for key, batch in queue.get("intake_batches", {}).items()},
            "retry_due": due, "ready_for_delivery": ready,
            "complete": not (counts["unreviewed"] or counts["blocked"] or ready),
            "can_expand_search": not (counts["unreviewed"] or due or ready)}


def next_items(workspace: WorkspacePaths, *, now: str, limit: int | None = None) -> list[dict]:
    current_time, approval = _time(now), review_context(workspace)
    results = []
    rows = sorted(load_queue(workspace)["items"].values(), key=lambda r: (r["first_seen_at"], r["review_id"]))
    for row in rows:
        status = _effective_status(row, approval)
        if not (status == "unreviewed" or (status == "qualifying" and not row.get("job_id"))
                or (status == "blocked" and _time(row["decision"]["retry_after"]) <= current_time)):
            continue
        observation = next(o for o in reversed(row["observations"]) if o["content_hash"] == row["content_hash"])
        path = (workspace.root / observation["snapshot"]).resolve()
        if not path.is_relative_to((workspace.sources / "discovery-review").resolve()):
            raise ValueError("snapshot_outside_workspace")
        raw = json.loads(path.read_text())
        if _digest(raw) != observation["snapshot_hash"]:
            raise ValueError("snapshot_hash_mismatch")
        results.append({**row, "expected_context": approval, "status": status, "raw": raw["raw"],
                        "raw_field_hash": raw["raw_field_hash"], "source_record_id": raw["source_record_id"],
                        "possible_existing_job_ids": possible_existing_jobs(workspace, row)})
        if limit is not None and len(results) >= limit:
            break
    return results


def validate_delivery(workspace: WorkspacePaths, payload: dict, *, now: str, require_delivered: bool = False) -> None:
    """Reject false completed sources and untracked/unreviewed publication."""
    queue = load_queue(workspace)
    approval = review_context(workspace)
    for source, result in payload.get("source_results", {}).items():
        rows = [r for r in queue["items"].values() if r["source"] == source or
                (source == "public_ats" and r["source"] in {"greenhouse", "lever", "ashby"})]
        intake_exists = source in queue.get("intakes", {}) or (source == "public_ats" and
            not {"greenhouse", "lever", "ashby"}.isdisjoint(queue.get("intakes", {})))
        if result.get("success") and (not intake_exists or any(
            _effective_status(r, approval) in {"unreviewed", "blocked"} or
            (require_delivered and _effective_status(r, approval) == "qualifying" and not r.get("job_id")) for r in rows)):
            raise ValueError("review_queue_incomplete:" + source)
        if result.get("success"):
            batch_ids = result.get("intake_ids")
            batches = queue.get("intake_batches", {})
            if not isinstance(batch_ids, (list, tuple)) or not batch_ids or any(b not in batches for b in batch_ids):
                raise ValueError("review_intake_receipts_required:" + source)
            allowed = {source} | ({"greenhouse", "lever", "ashby"} if source == "public_ats" else set())
            seen = set()
            for batch_id in batch_ids:
                batch = batches[batch_id]
                if batch["source"] not in allowed or _time(batch["captured_at"]) > _time(result.get("completed_at")):
                    raise ValueError("review_intake_scope_mismatch:" + source)
                seen.update(batch["source_record_ids"])
            if set(result.get("seen_records", ())) != seen:
                raise ValueError("review_intake_records_mismatch:" + source)
    for item in payload.get("reviewed", []):
        candidate = item["candidate"]
        rows = [r for r in queue["items"].values() if r["source"] == candidate["source"] and any(
            o["source_record_id"] == candidate["source_record_id"] and o["raw_field_hash"] == candidate["raw_field_hash"]
            and o["content_hash"] == r["content_hash"]
            for o in r["observations"])]
        if len(rows) != 1:
            raise ValueError("candidate_not_in_review_queue")
        status = _effective_status(rows[0], approval)
        disposition = (item.get("assessment") or {}).get("disposition")
        expected = "qualifying" if disposition in {"strong_match", "worth_considering"} else "non_match"
        if status != expected and not (expected == "non_match" and status == "excluded"):
            raise ValueError("candidate_review_not_completed")


def mark_delivered(workspace: WorkspacePaths, candidate: dict, job_id: str) -> None:
    """An interrupted delivery is safe to replay through canonical deduplication."""
    with workspace_lock(workspace):
        queue = load_queue(workspace)
        for row in queue["items"].values():
            if row["source"] == candidate["source"] and row["status"] == "qualifying" and any(
                    o["source_record_id"] == candidate["source_record_id"] and o["raw_field_hash"] == candidate["raw_field_hash"]
                    and o["content_hash"] == row["content_hash"]
                    for o in row["observations"]):
                row["job_id"] = job_id
        atomic_write_json(workspace.state / _FILE, queue)
