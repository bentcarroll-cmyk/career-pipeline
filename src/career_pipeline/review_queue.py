"""Durable discovery intake, explicit review outcomes, and resumable delivery.

This ledger tracks work, not canonical job identity. Employer/title hints must
be verified by a reviewer; they never suppress a listing or allocate a JOB.
"""
from __future__ import annotations

import hashlib
import json
import re
import copy
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
    if _mixed_posting_ids(row) or row.get("snapshot_selection_required") or row.get("capture_time_conflict"):
        return "unreviewed"
    if row.get("decision") and row.get("approval_fingerprint") != approval:
        return "unreviewed"
    if _automatic_location_decision(row):
        from .location_prefilter import MATCHER_VERSION
        if row["decision"]["prefilter"].get("matcher_version") != MATCHER_VERSION:
            return "unreviewed"
    return row["status"]


def _automatic_location_decision(row: dict) -> bool:
    decision = row.get("decision") or {}
    return (decision.get("status") == "excluded"
            and decision.get("reason_code") == "nonlocal_without_remote_option"
            and isinstance(decision.get("prefilter"), dict)
            and decision["prefilter"].get("policy") == "exclude_nonlocal_without_remote_option")


def _mixed_posting_ids(row: dict) -> bool:
    return len({o["source_record_id"] for o in row["observations"]}) > 1


def _posting_key(raw: dict) -> str:
    identity = [_normalize(raw[k]) for k in ("source", "employer", "title", "location", "requisition_id")]
    # Provider IDs are scoped by source and posting context. A shared requisition
    # is a reviewer hint, never authority to combine independent posting IDs.
    return "review:" + _digest([*identity, raw["source_record_id"]])


def _content_hash(raw: dict, *, version: int = 1) -> str:
    material = {k: v for k, v in raw["raw"].items()
                if k not in {"jrtk", "url", "posted_date", "sponsored", "company_rating", "advertiser_name"}}
    return _digest(material if version == 1 else {"material": material, "posting_url": raw["posting_url"]})


def _current_observation(row: dict) -> dict:
    active = row.get("active_snapshot_hash")
    for observation in reversed(row["observations"]):
        if observation["content_hash"] == row["content_hash"] and (active is None or observation["snapshot_hash"] == active):
            return observation
    raise ValueError("snapshot_identity_mismatch")


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


def ingest(workspace: WorkspacePaths, records: list[dict], *, now: str, source: str | None = None,
           replay: bool = False) -> dict:
    """Save every record; historical recovery cannot replace newer active evidence.

    At equal capture times a fresh intake establishes order under the lock, but
    a differing replay requires a later capture before review can be completed.
    """
    _time(now)
    prepared = [_intake(r) for r in records]  # Validate the whole batch before writing.
    if source is not None and (not source.strip() or any(r["source"] != source for r in prepared)):
        raise ValueError("intake_source_mismatch")
    with workspace_lock(workspace):
        queue = load_queue(workspace)
        touched = set()
        for name in ({r["source"] for r in prepared} | ({source} if source else set())):
            previous = queue.setdefault("intakes", {}).get(name)
            if (previous is None or _time(now) > _time(previous["captured_at"])
                    or (_time(now) == _time(previous["captured_at"]) and not replay)):
                queue["intakes"][name] = dict(captured_at=now, returned_records=sum(r["source"] == name for r in prepared))
            receipt = dict(source=name, captured_at=now, source_record_ids=sorted({r["source_record_id"] for r in prepared if r["source"] == name}),
                           snapshot_hashes=sorted({_digest(r) for r in prepared if r["source"] == name}))
            queue.setdefault("intake_batches", {})[_digest(receipt)] = receipt
        for raw in prepared:
            key = _posting_key(raw)
            # Preserve references to unambiguous legacy rows in the same posting
            # context. Opaque provider handles can recur across employers.
            existing = [r for r in queue["items"].values() if all(_normalize(r[k]) == _normalize(raw[k])
                        for k in ("source", "employer", "title", "location", "requisition_id")) and
                        any(o["source_record_id"] == raw["source_record_id"] for o in r["observations"])]
            if any(_mixed_posting_ids(r) for r in existing):
                raise ValueError("posting_identity_recovery_required")
            if len(existing) == 1:
                key = existing[0]["review_id"]
            row = queue["items"].get(key)
            version = row.get("content_hash_version", 1) if row else 2
            url_changed = row is not None and row["posting_url"] != raw["posting_url"]
            if url_changed:
                version = 2
            content_hash = _content_hash(raw, version=version)
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
            observed = row and any(x["snapshot_hash"] == snapshot_hash and x["content_hash"] == content_hash
                                   for x in row["observations"])
            ambiguous_time = row and _time(now) == _time(row["last_seen_at"]) and (
                replay or row.get("capture_time_conflict"))
            if ambiguous_time and (row["content_hash"] != content_hash or url_changed):
                prior = row.get("capture_time_conflict", {})
                row["capture_time_conflict"] = {
                    "captured_at": row["last_seen_at"],
                    "snapshot_hashes": sorted({*prior.get("snapshot_hashes", ()), snapshot_hash,
                                               _current_observation(row)["snapshot_hash"]}),
                }
            if row and (_time(now) < _time(row["last_seen_at"]) or ambiguous_time):
                # Observation timestamps are deduplicated. The active snapshot
                # may have been observed again later (A -> B -> A), so compare
                # with last_seen_at rather than the snapshot's first timestamp.
                if not observed:
                    row["observations"].append(observation)
                row["first_seen_at"] = min((row["first_seen_at"], now), key=_time)
                continue
            resolving_capture_time = bool(row and row.get("capture_time_conflict")
                and _time(now) > _time(row["capture_time_conflict"]["captured_at"]))
            resolving_snapshot = bool(row and row.get("snapshot_selection_required")
                and _time(now) > _time(row["identity_recovery"]["recovered_at"]))
            if row and row.get("snapshot_selection_required") and not resolving_snapshot:
                # Replaying an old immutable capture does not establish which
                # of a legacy posting's different bodies is current.
                if not observed:
                    row["observations"].append(observation)
                row["last_seen_at"] = max((row["last_seen_at"], now), key=_time)
                touched.add(key)
                continue
            if row is None:
                row = {k: raw[k] for k in ("source", "employer", "title", "location", "requisition_id", "posting_url")}
                row.update(review_id=key, revision=1, status="unreviewed", first_seen_at=now,
                           content_hash=content_hash, content_hash_version=version,
                           observations=[], history=[], decision=None)
                queue["items"][key] = row
            elif row["content_hash"] != content_hash or url_changed or resolving_snapshot or resolving_capture_time:
                row["history"].append({k: row.get(k) for k in ("revision", "decision", "content_hash", "job_id", "approval_fingerprint", "posting_url", "snapshot_selection_required", "capture_time_conflict")})
                row.update(revision=row["revision"] + 1, content_hash=content_hash,
                           content_hash_version=version, posting_url=raw["posting_url"],
                           status="unreviewed", decision=None)
                row.pop("job_id", None)
            if url_changed:
                row["posting_url_changed"] = True
            if resolving_snapshot:
                row.pop("snapshot_selection_required", None)
                row["identity_recovery"].update(resolved_at=now, resolved_snapshot_hash=snapshot_hash)
            if resolving_capture_time:
                row.pop("capture_time_conflict", None)
            # One immutable snapshot can carry both legacy and current content
            # hashes. Retain the versioned observation needed by the active row.
            if not observed:
                row["observations"].append(observation)
            row["last_seen_at"] = now
            row["active_snapshot_hash"] = snapshot_hash
            touched.add(key)
        from .criteria import CriteriaError
        try:
            _apply_location_prefilter_locked(workspace, queue, now=now, review_ids=touched)
        except CriteriaError:
            # Invalid or unapproved optional criteria cannot discard source
            # intake. Its complete records remain pending for manual review.
            pass
        except ValueError:
            # Context drift must not erase captures that already completed.
            atomic_write_json(workspace.state / _FILE, queue)
            raise
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


def _recovery_rows(workspace: WorkspacePaths, queue: dict, review_ids: list[str]) -> tuple[list[dict], dict]:
    """Validate every snapshot and construct replacement rows without writing."""
    splits, replacements = [], {}
    for review_id in review_ids:
        original = queue["items"].get(review_id)
        if original is None or not _mixed_posting_ids(original):
            raise ValueError("mixed_posting_review_required")
        groups = {}
        for observation in original["observations"]:
            path = (workspace.root / observation["snapshot"]).resolve()
            if not path.is_relative_to((workspace.sources / "discovery-review").resolve()):
                raise ValueError("snapshot_outside_workspace")
            raw = json.loads(path.read_text(encoding="utf-8"))
            if _digest(raw) != observation["snapshot_hash"]:
                raise ValueError("snapshot_hash_mismatch")
            prepared = _intake(raw)
            if (prepared != raw or raw["source"] != original["source"]
                    or raw["source_record_id"] != observation["source_record_id"]
                    or raw["raw_field_hash"] != observation["raw_field_hash"]
                    or observation["content_hash"] not in {_content_hash(raw), _content_hash(raw, version=2)}):
                raise ValueError("snapshot_identity_mismatch")
            _time(observation["captured_at"])
            key = _posting_key(raw)
            groups.setdefault(key, []).append((observation, raw))
        active_snapshot = original.get("active_snapshot_hash")
        current_groups = {key: [(o, raw) for o, raw in entries
                               if o["content_hash"] == original["content_hash"]
                               and (active_snapshot is None or o["snapshot_hash"] == active_snapshot)]
                          for key, entries in groups.items()}
        current_groups = {key: entries for key, entries in current_groups.items() if entries}
        if not current_groups:
            raise ValueError("snapshot_identity_mismatch")
        known_current_key = next(iter(current_groups)) if len(current_groups) == 1 else None
        held = {}
        for key, entries in groups.items():
            if key in replacements or key in queue["items"]:
                raise ValueError("posting_identity_recovery_collision")
            current_entries = current_groups[key] if key == known_current_key else entries
            # Legacy hashes omit URL, so even a unique matching posting group
            # may contain several different current-snapshot candidates.
            uncertain = len({_content_hash(raw, version=2) for _, raw in current_entries}) > 1
            # Deduplicated observation timestamps cannot reconstruct A -> B -> A.
            # Use the parent's provable current body, or hold multiple versions.
            latest, raw = current_entries[-1]
            row = {k: raw[k] for k in ("source", "employer", "title", "location", "requisition_id", "posting_url")}
            row.update(review_id=key, revision=original["revision"] + 1, status="unreviewed",
                       first_seen_at=min((o["captured_at"] for o, _ in entries), key=_time),
                       last_seen_at=max((o["captured_at"] for o, _ in entries), key=_time),
                       content_hash=latest["content_hash"],
                       content_hash_version=2 if latest["content_hash"] == _content_hash(raw, version=2) else 1,
                       observations=[copy.deepcopy(o) for o, _ in entries], history=[], decision=None,
                       identity_recovery={"from_review_id": review_id, "from_revision": original["revision"]})
            if uncertain:
                row["snapshot_selection_required"] = True
                held[key] = [{k: o[k] for k in ("snapshot", "snapshot_hash", "content_hash", "captured_at")}
                             for o, _ in entries]
            else:
                row["active_snapshot_hash"] = latest["snapshot_hash"]
            replacements[key] = row
        splits.append({"review_id": review_id, "source": original["source"],
                       "source_record_ids": sorted({o["source_record_id"] for o in original["observations"]}),
                       "replacement_review_ids": sorted(groups), "observations": len(original["observations"]),
                       "prior_status": original["status"], "prior_job_id": original.get("job_id"),
                       "replacement_status": "unreviewed", "snapshot_selection_required": held})
    return splits, replacements


def _recovery_ids(queue: dict, review_ids: list[str] | None) -> list[str]:
    if review_ids is None:
        return sorted(key for key, row in queue["items"].items() if _mixed_posting_ids(row))
    if (not isinstance(review_ids, list) or not review_ids
            or any(not isinstance(key, str) or not re.fullmatch(r"review:[a-f0-9]{64}", key) for key in review_ids)
            or len(set(review_ids)) != len(review_ids)):
        raise ValueError("bounded_recovery_review_ids_required")
    return sorted(review_ids)


def plan_posting_identity_recovery(workspace: WorkspacePaths, *, review_ids: list[str] | None = None) -> dict:
    """Read-only preview of mixed rows, with an exact queue fingerprint for apply."""
    with workspace_lock(workspace):
        queue = load_queue(workspace)
        selected = _recovery_ids(queue, review_ids)
        splits, _ = _recovery_rows(workspace, queue, selected)
        return {"expected_queue_hash": _digest(queue), "review_ids": selected, "splits": splits}


def recover_posting_identities(workspace: WorkspacePaths, *, review_ids: list[str],
                               expected_queue_hash: str, now: str) -> dict:
    """Atomically split a reviewed plan; retain original evidence and replay safely.

    Recovery changes only this queue. Prior decisions and delivery references are
    retained in identity_recovery_history and never inherited by replacements.
    """
    _time(now)
    if not isinstance(expected_queue_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_queue_hash):
        raise ValueError("recovery_queue_hash_required")
    with workspace_lock(workspace):
        queue = load_queue(workspace)
        selected = _recovery_ids(queue, review_ids)
        recovery_id = _digest({"review_ids": selected, "expected_queue_hash": expected_queue_hash})
        previous = queue.get("identity_recoveries", {}).get(recovery_id)
        if previous is not None:
            return {**previous, "replayed": True}
        if _digest(queue) != expected_queue_hash:
            raise ValueError("stale_recovery_plan")
        splits, replacements = _recovery_rows(workspace, queue, selected)
        for split in splits:
            review_id = split["review_id"]
            if review_id in queue.get("identity_recovery_history", {}):
                raise ValueError("posting_identity_recovery_collision")
            queue.setdefault("identity_recovery_history", {})[review_id] = {
                "original_item": queue["items"].pop(review_id), "recovery_id": recovery_id,
                "recovered_at": now, "replacement_review_ids": split["replacement_review_ids"]}
        for row in replacements.values():
            row["identity_recovery"]["recovered_at"] = now
        queue["items"].update(replacements)
        result = {"recovery_id": recovery_id, "expected_queue_hash": expected_queue_hash,
                  "review_ids": selected, "splits": splits,
                  "recovered_review_ids": sorted(replacements), "recovered_at": now, "replayed": False}
        queue.setdefault("identity_recoveries", {})[recovery_id] = result
        atomic_write_json(workspace.state / _FILE, queue)
        return result


def _validate_decision(decision: dict, *, now: str) -> None:
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


def _set_decision(row: dict, decision: dict | None, *, approval: str, now: str) -> None:
    row["history"].append({k: row.get(k) for k in ("revision", "decision", "approval_fingerprint", "job_id")})
    row.pop("job_id", None)
    row.update(status=decision["status"] if decision else "unreviewed", decision=decision, revision=row["revision"] + 1)
    if decision is None:
        row.pop("reviewed_at", None)
        row.pop("approval_fingerprint", None)
    else:
        row.update(reviewed_at=now, approval_fingerprint=approval)


def record_decision(workspace: WorkspacePaths, review_id: str, decision: dict,
                    *, expected_revision: int, expected_context: str, now: str) -> dict:
    """Resolve actual work, or record a specific observed blocker with a retry."""
    _validate_decision(decision, now=now)
    with workspace_lock(workspace):
        if expected_context != review_context(workspace):
            raise ValueError("stale_review_context")
        queue = load_queue(workspace)
        row = queue["items"].get(review_id)
        if row is None or row["revision"] != expected_revision:
            raise ValueError("stale_review_revision")
        if _mixed_posting_ids(row):
            raise ValueError("posting_identity_recovery_required")
        if row.get("snapshot_selection_required"):
            raise ValueError("posting_snapshot_selection_required")
        if row.get("capture_time_conflict"):
            raise ValueError("capture_time_conflict_requires_fresh_capture:" + review_id)
        if decision["status"] == "qualifying" and possible_existing_jobs(workspace, row) and len(decision.get("identity_resolution", "")) < 20:
            raise ValueError("identity_resolution_required")
        _set_decision(row, decision, approval=expected_context, now=now)
        atomic_write_json(workspace.state / _FILE, queue)
        return row


def _apply_location_prefilter_locked(workspace: WorkspacePaths, queue: dict, *, now: str,
                                     review_ids=None, dry_run: bool = False) -> dict:
    from .criteria import resolve_workspace_criteria
    from .location_prefilter import exclusion_decision
    approval = review_context(workspace)
    criteria = resolve_workspace_criteria(workspace)
    scope = criteria.discovery_location_scope if criteria else None
    report = {"policy_enabled": scope is not None, "dry_run": dry_run, "considered": 0,
              "excluded": 0, "would_exclude": 0, "decisions": [],
              "reopened": 0, "would_reopen": 0, "reopen_review_ids": [],
              "held": {"existing_decision": 0, "mixed_posting_ids": 0,
                       "snapshot_selection_required": 0, "snapshot_invalid": 0, "capture_time_conflict": 0}}
    for key, row in queue["items"].items():
        if review_ids is not None and key not in review_ids:
            continue
        if _mixed_posting_ids(row):
            report["held"]["mixed_posting_ids"] += 1
            continue
        if row.get("snapshot_selection_required"):
            report["held"]["snapshot_selection_required"] += 1
            continue
        if row.get("capture_time_conflict"):
            report["held"]["capture_time_conflict"] += 1
            continue
        status = _effective_status(row, approval)
        stale_automatic = _automatic_location_decision(row) and status == "unreviewed"
        # Manual decisions require explicit reassessment. An old automatic
        # exclusion can be re-evaluated against the current approved policy.
        if (row.get("decision") is not None and not stale_automatic) or status != "unreviewed":
            report["held"]["existing_decision"] += 1
            continue
        if scope is None and not stale_automatic:
            continue
        report["considered"] += 1
        try:
            observation = _current_observation(row)
            path = (workspace.root / observation["snapshot"]).resolve()
            if not path.is_relative_to((workspace.sources / "discovery-review").resolve()):
                raise ValueError("snapshot_outside_workspace")
            raw = json.loads(path.read_text(encoding="utf-8"))
            if _digest(raw) != observation["snapshot_hash"]:
                raise ValueError("snapshot_hash_mismatch")
            if (_intake(raw) != raw or raw["source_record_id"] != observation["source_record_id"]
                    or raw["raw_field_hash"] != observation["raw_field_hash"]
                    or any(raw[k] != row[k] for k in ("source", "employer", "title", "location", "requisition_id", "posting_url"))
                    or _content_hash(raw, version=row.get("content_hash_version", 1)) != row["content_hash"]):
                raise ValueError("snapshot_identity_mismatch")
        except (OSError, ValueError, KeyError, TypeError, StopIteration):
            report["held"]["snapshot_invalid"] += 1
            continue
        decision = exclusion_decision(raw, scope) if scope else None
        if decision is None:
            if stale_automatic:
                report["reopen_review_ids"].append(key)
            continue
        decision["prefilter"].update(snapshot_hash=observation["snapshot_hash"],
                                    reviewed_revision=row["revision"], expected_context=approval)
        _validate_decision(decision, now=now)
        report["decisions"].append({"review_id": key, "expected_revision": row["revision"],
                                  "expected_context": approval, "decision": decision})
    # All classifier outputs are staged before any row changes, so a stale
    # context cannot leave part of a batch carrying an outdated exclusion.
    if approval != review_context(workspace):
        raise ValueError("stale_review_context")
    report["would_exclude"] = len(report["decisions"])
    report["would_reopen"] = len(report["reopen_review_ids"])
    if not dry_run:
        for proposed in report["decisions"]:
            _set_decision(queue["items"][proposed["review_id"]], proposed["decision"], approval=approval, now=now)
        for key in report["reopen_review_ids"]:
            _set_decision(queue["items"][key], None, approval=approval, now=now)
        report["excluded"] = report["would_exclude"]
        report["reopened"] = report["would_reopen"]
    return report


def apply_location_prefilter(workspace: WorkspacePaths, *, now: str, dry_run: bool = False) -> dict:
    """Apply approved geography exclusions once to pending, intact snapshots."""
    _time(now)
    with workspace_lock(workspace):
        queue = load_queue(workspace)
        report = _apply_location_prefilter_locked(workspace, queue, now=now, dry_run=dry_run)
        if report["excluded"] or report["reopened"]:
            atomic_write_json(workspace.state / _FILE, queue)
        return report


def summary(workspace: WorkspacePaths, *, now: str) -> dict:
    with workspace_lock(workspace):
        return _summary_locked(workspace, now=now)


def _summary_locked(workspace: WorkspacePaths, *, now: str) -> dict:
    current_time = _time(now)
    queue = load_queue(workspace)
    rows = list(queue["items"].values())
    approval = review_context(workspace)
    counts = Counter(_effective_status(row, approval) for row in rows)
    due = sum(_effective_status(row, approval) == "blocked" and
              _time(row["decision"]["retry_after"]) <= current_time for row in rows)
    ready = sum(_effective_status(row, approval) == "qualifying" and not row.get("job_id") for row in rows)
    from .retrieval import summary as retrieval_summary
    retrieval = retrieval_summary(workspace, now=now)
    review_complete = not (counts["unreviewed"] or counts["blocked"] or ready)
    return {"total": len(rows), **{status: counts[status] for status in sorted(_STATUSES)},
            "intake_batches": {key: {"source": batch["source"], "captured_at": batch["captured_at"],
                "returned_records": len(batch["source_record_ids"])} for key, batch in queue.get("intake_batches", {}).items()},
            "retry_due": due, "ready_for_delivery": ready,
            "review_complete": review_complete, "retrieval": retrieval,
            "complete": review_complete and retrieval["complete"],
            "can_expand_search": not (counts["unreviewed"] or due or ready)}


def next_items(workspace: WorkspacePaths, *, now: str, limit: int | None = None) -> list[dict]:
    current_time, approval = _time(now), review_context(workspace)
    results = []
    rows = sorted(load_queue(workspace)["items"].values(), key=lambda r: (r["first_seen_at"], r["review_id"]))
    for row in rows:
        if _mixed_posting_ids(row):
            raise ValueError("posting_identity_recovery_required")
        if row.get("snapshot_selection_required"):
            raise ValueError("posting_snapshot_selection_required")
        if row.get("capture_time_conflict"):
            raise ValueError("capture_time_conflict_requires_fresh_capture:" + row["review_id"])
        status = _effective_status(row, approval)
        if not (status == "unreviewed" or (status == "qualifying" and not row.get("job_id"))
                or (status == "blocked" and _time(row["decision"]["retry_after"]) <= current_time)):
            continue
        observation = _current_observation(row)
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
        allowed = {source}
        if source == "public_ats":
            from .retrieval import load_ledger
            allowed.update({"greenhouse", "lever", "ashby"})
            allowed.update(s["source"] for s in load_ledger(workspace)["scopes"].values()
                           if s["provider"] in {"greenhouse", "lever", "ashby"})
        rows = [r for r in queue["items"].values() if r["source"] in allowed]
        intake_exists = not allowed.isdisjoint(queue.get("intakes", {}))
        if result.get("success") and (not intake_exists or any(
            _effective_status(r, approval) in {"unreviewed", "blocked"} or
            (require_delivered and _effective_status(r, approval) == "qualifying" and not r.get("job_id")) for r in rows)):
            raise ValueError("review_queue_incomplete:" + source)
        if result.get("success"):
            from .retrieval import validate_source_result
            validate_source_result(workspace, source, result, now=now)
            batch_ids = result.get("intake_ids")
            batches = queue.get("intake_batches", {})
            if not isinstance(batch_ids, (list, tuple)) or not batch_ids or any(b not in batches for b in batch_ids):
                raise ValueError("review_intake_receipts_required:" + source)
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
        rows = [r for r in queue["items"].values() if _candidate_matches(r, candidate)]
        if len(rows) != 1:
            raise ValueError("candidate_not_in_review_queue")
        status = _effective_status(rows[0], approval)
        disposition = (item.get("assessment") or {}).get("disposition")
        expected = "qualifying" if disposition in {"strong_match", "worth_considering"} else "non_match"
        if status != expected and not (expected == "non_match" and status == "excluded"):
            raise ValueError("candidate_review_not_completed")


def _candidate_matches(row: dict, candidate: dict) -> bool:
    if row["source"] != candidate["source"]:
        return False
    if row.get("posting_url_changed") and candidate.get("posting_url") != row["posting_url"]:
        return False
    return any(o["source_record_id"] == candidate["source_record_id"]
               and o["raw_field_hash"] == candidate["raw_field_hash"]
               and o["content_hash"] == row["content_hash"] for o in row["observations"])


def mark_delivered(workspace: WorkspacePaths, candidate: dict, job_id: str) -> None:
    """An interrupted delivery is safe to replay through canonical deduplication."""
    with workspace_lock(workspace):
        queue = load_queue(workspace)
        matches = [row for row in queue["items"].values() if _candidate_matches(row, candidate)]
        if any(_mixed_posting_ids(row) for row in matches):
            raise ValueError("posting_identity_recovery_required")
        if any(row.get("snapshot_selection_required") for row in matches):
            raise ValueError("posting_snapshot_selection_required")
        if any(row.get("capture_time_conflict") for row in matches):
            raise ValueError("capture_time_conflict_requires_fresh_capture:" + matches[0]["review_id"])
        if len(matches) != 1:
            raise ValueError("candidate_not_in_review_queue")
        row = matches[0]
        if _effective_status(row, review_context(workspace)) != "qualifying":
            return
        row["job_id"] = job_id
        atomic_write_json(workspace.state / _FILE, queue)
