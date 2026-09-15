"""Provider response evidence and resumable, fail-closed retrieval accounting."""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass

from .atomic import atomic_write_json
from .collectors import validate_board_query
from .job_store import workspace_lock_if_needed as workspace_lock
from .source_pages import NORMALIZATION_VERSION
from . import review_queue as queue

_FILE = "discovery-retrieval.json"
_BOARD_PROVIDERS = {"greenhouse", "lever", "ashby"}
_PROVIDERS = _BOARD_PROVIDERS | {"indeed", "unstructured"}


def _source_provider(source, provider):
    if (source in _PROVIDERS and source != provider) or (source == "public_ats" and provider not in _BOARD_PROVIDERS):
        raise ValueError("retrieval_source_provider_mismatch")


def load_ledger(workspace) -> dict:
    path = workspace.state / _FILE
    if not path.exists():
        return {"schema_version": 1, "scopes": {}}
    try:
        ledger = json.loads(path.read_text())
        if ledger.get("schema_version") != 1 or not isinstance(ledger.get("scopes"), dict):
            raise ValueError()
        for key, row in ledger["scopes"].items():
            identity = {k: row[k] for k in ("run_id", "source", "provider", "query")}
            if key != "scope:" + queue._digest(identity) or row["scope_id"] != key:
                raise ValueError()
            if row["provider"] not in _PROVIDERS or not isinstance(row["pages"], list):
                raise ValueError()
            _source_provider(row["source"], row["provider"])
        return ledger
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ValueError("retrieval_ledger_invalid") from exc


def _save(workspace, ledger):
    atomic_write_json(workspace.state / _FILE, ledger)


def _scope(ledger, scope_id):
    if scope_id not in ledger["scopes"]:
        raise ValueError("retrieval_scope_unknown")
    return ledger["scopes"][scope_id]


def _snapshot(workspace, value):
    digest = queue._digest(value)
    path = workspace.sources / "discovery-retrieval" / f"{digest}.json"
    if not path.resolve().is_relative_to(workspace.sources.resolve()):
        raise ValueError("retrieval_snapshot_outside_workspace")
    if path.exists():
        _read_snapshot(workspace, {"snapshot": path.relative_to(workspace.root).as_posix(), "snapshot_hash": digest})
    else:
        atomic_write_json(path, value)
    return {"snapshot": path.relative_to(workspace.root).as_posix(), "snapshot_hash": digest}


def _read_snapshot(workspace, ref):
    try:
        path = (workspace.root / ref["snapshot"]).resolve()
        if not path.is_relative_to((workspace.sources / "discovery-retrieval").resolve()):
            raise ValueError()
        value = json.loads(path.read_text())
        if queue._digest(value) != ref["snapshot_hash"]:
            raise ValueError()
        return value
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ValueError("retrieval_snapshot_integrity_error") from exc


def _page_version(page):
    version = page.get("normalization_version", 1)
    if type(version) is not int or version not in (1, NORMALIZATION_VERSION):
        raise ValueError("retrieval_normalization_version_invalid")
    return version


def _parse(scope, response, cursor, *, normalization_version=NORMALIZATION_VERSION):
    from .source_pages import parse_page
    if scope["provider"] in _BOARD_PROVIDERS:
        validate_board_query(scope["provider"], scope["query"])
    parsed = parse_page(scope["provider"], response, query=scope["query"], cursor=cursor,
                        normalization_version=normalization_version)
    parsed["records"] = [{**r, "source": scope["source"]} for r in parsed["records"]]
    return parsed


def _partition(scope, records):
    complete, pointers, nonpublic = [], [], []
    for record in records:
        if scope["provider"] == "ashby" and record.get("raw", {}).get("isListed") is False:
            nonpublic.append({"source_record_id": record["source_record_id"], "reason": "provider_unlisted"})
            continue
        try:
            complete.append(queue._intake(record))
        except ValueError:
            pointers.append(record)
    return complete, pointers, nonpublic


def _normalization_records(scope, page, response, original):
    """Reproduce only changed complete records; explicit pointer resolutions win."""
    if _page_version(page) == NORMALIZATION_VERSION:
        return []
    old, _, _ = _partition(scope, original["records"])
    old = {record["source_record_id"]: record for record in old}
    current = _parse(scope, response, page["cursor"])
    complete, _, _ = _partition(scope, current["records"])
    return [record for record in complete
            if record["source_record_id"] not in scope.get("resolutions", {})
            and old.get(record["source_record_id"]) != record]


def _normalization_snapshot(page, records):
    return {"page_snapshot_hash": page["snapshot_hash"],
            "normalization_version": NORMALIZATION_VERSION, "records": records}


def _normalization_conflicts(workspace, page, records, q, *, current, original_records):
    """Old native content cannot supersede a newer observation of this posting."""
    conflicts = set()
    # Equal timestamps do not prove order. Exempt only exact legacy receipts.
    original_hashes = {queue._digest(record) for record in original_records}
    for record in records:
        for row in q["items"].values():
            if any(queue._normalize(row.get(key)) != queue._normalize(record.get(key))
                   for key in ("source", "employer", "title", "location", "requisition_id")):
                continue
            for observation in row["observations"]:
                at = queue._time(observation["captured_at"])
                if (observation["source_record_id"] != record["source_record_id"]
                        or at < queue._time(page["captured_at"]) or at > current
                        or observation["snapshot_hash"] in original_hashes):
                    continue
                try:
                    path = (workspace.root / observation["snapshot"]).resolve()
                    if not path.is_relative_to((workspace.sources / "discovery-review").resolve()):
                        raise ValueError()
                    newer = json.loads(path.read_text())
                    if (queue._digest(newer) != observation["snapshot_hash"] or queue._intake(newer) != newer
                            or any(newer.get(key) != record.get(key) for key in ("source", "source_record_id"))
                            or newer["raw_field_hash"] != observation["raw_field_hash"]):
                        raise ValueError()
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    raise ValueError("retrieval_newer_observation_invalid") from exc
                if queue._content_hash(newer, version=2) != queue._content_hash(record, version=2):
                    conflicts.add(record["source_record_id"])
    return conflicts


def _audit_normalization(workspace, scope, page, records, *, current, q, observations):
    repair = page.get("normalization_repair")
    if "normalization_repair" not in page:
        return None
    if (not records or not isinstance(repair, dict)
            or type(repair.get("normalization_version")) is not int
            or repair["normalization_version"] != NORMALIZATION_VERSION
            or repair.get("page_snapshot_hash") != page["snapshot_hash"]
            or repair.get("status") not in {"captured", "ingested"}):
        raise ValueError("retrieval_normalization_repair_invalid")
    if (_read_snapshot(workspace, repair) != _normalization_snapshot(page, records)
            or queue._time(repair["captured_at"]) < queue._time(page["captured_at"])
            or queue._time(repair["captured_at"]) > current):
        raise ValueError("retrieval_normalization_repair_mismatch")
    if repair["status"] == "captured":
        return None
    return _check_receipt(workspace, q, observations, scope["source"], records,
                          repair["captured_at"], repair.get("intake_ids"))


def _receipt(source, records, now):
    return {"source": source, "captured_at": now,
            "source_record_ids": sorted({r["source_record_id"] for r in records}),
            "snapshot_hashes": sorted({queue._digest(r) for r in records})}


def _observations(q):
    return {(row["source"], o["source_record_id"], o["snapshot_hash"])
            for row in q["items"].values() for o in row["observations"]}


def _check_receipt(workspace, q, observations, source, records, at, receipt_ids):
    receipt = _receipt(source, records, at)
    key = queue._digest(receipt)
    if receipt_ids != [key] or q.get("intake_batches", {}).get(key) != receipt:
        raise ValueError("retrieval_intake_receipt_mismatch")
    for record in records:
        digest = queue._digest(record)
        path = workspace.sources / "discovery-review" / f"{digest}.json"
        try:
            if not path.resolve().is_relative_to((workspace.sources / "discovery-review").resolve()):
                raise ValueError()
            if queue._digest(json.loads(path.read_text())) != digest:
                raise ValueError()
        except (OSError, ValueError) as exc:
            raise ValueError("retrieval_intake_snapshot_mismatch") from exc
        if (source, record["source_record_id"], digest) not in observations:
            raise ValueError("retrieval_intake_observation_missing")
    return key


def _invalid_evidence(scope, response, cursor, *, normalization_version=NORMALIZATION_VERSION):
    """Identify conservative lower bounds without treating a malformed page as valid."""
    provider = scope["provider"]
    payload = response.get("structuredContent", response) if provider == "indeed" and isinstance(response, dict) else response
    total = None
    if provider == "greenhouse" and isinstance(payload, dict):
        meta = payload.get("meta")
        if isinstance(meta, dict) and type(meta.get("total")) is int and meta["total"] >= 0:
            total = meta["total"]
    if provider == "lever":
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("extracted_listings" if provider == "unstructured" else "jobs", [])
    else:
        rows = []
    if not isinstance(rows, list):
        return set(), True, total
    ids, unknown = set(), False
    for row in rows:
        singleton = [row] if provider == "lever" else {"jobs": [row]}
        if provider == "unstructured":
            singleton = {"raw_response": payload.get("raw_response"), "extracted_listings": [row]}
        try:
            parsed = _parse(scope, singleton, cursor, normalization_version=normalization_version)
            ids.update(record["source_record_id"] for record in parsed["records"])
        except (ValueError, TypeError, KeyError):
            unknown = True
    return ids, unknown, total


def _active_failures(scope):
    return scope.get("active_failures", [scope["failure"]] if scope.get("failure") else [])


def _set_active_failures(scope, failures):
    scope["active_failures"] = failures
    if failures:
        scope["failure"] = failures[-1]
    else:
        scope.pop("failure", None)


def _audit(workspace, scope, *, now, review_queue=None, observations=None):
    """Re-derive accounting from immutable evidence, never saved completion flags."""
    if scope["provider"] in _BOARD_PROVIDERS:
        validate_board_query(scope["provider"], scope["query"])
    current = queue._time(now)
    q = queue.load_queue(workspace) if review_queue is None else review_queue
    observations = _observations(q) if observations is None else observations
    returned, public, receipts, pointers, nonpublic, pending = set(), set(), [], {}, [], []
    normalization_pages, pointer_times, repairable = [], {}, set()
    exhausted, expected_cursor, total = False, None, None
    invalid_ids, unresolved_invalid = set(), False
    accepted = 0
    for page_index, page in enumerate(scope["pages"]):
        response = _read_snapshot(workspace, page)
        version = _page_version(page)
        if "normalization_repair" in page and page.get("status") != "ingested":
            raise ValueError("retrieval_normalization_repair_invalid")
        if queue._time(page["captured_at"]) < queue._time(scope["registered_at"]) or queue._time(page["captured_at"]) > current:
            raise ValueError("retrieval_capture_time_invalid")
        if page.get("status") == "invalid":
            original_ids, unknown_rows, original_total = _invalid_evidence(
                scope, response, page["cursor"], normalization_version=version)
            invalid_ids.update(original_ids)
            retries = [_parse(scope, _read_snapshot(workspace, p), p["cursor"], normalization_version=_page_version(p))
                       for p in scope["pages"][page_index + 1:]
                       if p["status"] == "ingested" and p["cursor"] == page["cursor"]]
            retry_ids = {r["source_record_id"] for parsed in retries for r in parsed["records"]}
            retried = bool(retries) and not unknown_rows and original_ids <= retry_ids and (
                original_total is None or len(retry_ids) == original_total)
            if not retried:
                unresolved_invalid = True
                pending.append({"reason": page.get("error", "malformed_response"),
                    "cursor": page["cursor"], "snapshot": page["snapshot"],
                    "source_record_ids": sorted(original_ids), "unaccounted_source_record_ids": sorted(original_ids - retry_ids),
                    "unidentified_rows": unknown_rows,
                    "next_action": "Retry this exact cursor; unexpected or changed accepted pages need explicit investigation."})
            continue  # Failed attempts remain durable; a valid retry may replace them.
        if page.get("status") != "ingested":
            pending.append({"reason": "ingestion_interrupted", "next_action": "Replay the saved response and cursor.", "snapshot": page["snapshot"]})
            continue
        parsed = _parse(scope, response, page["cursor"], normalization_version=version)
        if exhausted or page["cursor"] != expected_cursor:
            raise ValueError("retrieval_cursor_sequence_invalid")
        ids = {r["source_record_id"] for r in parsed["records"]}
        if ids & returned:
            raise ValueError("retrieval_duplicate_page_records")
        returned.update(ids)
        if parsed["reported_total"] is not None:
            if total is not None and total != parsed["reported_total"]:
                raise ValueError("retrieval_reported_total_changed")
            total = parsed["reported_total"]
        complete, missing, unlisted = _partition(scope, parsed["records"])
        receipts.append(_check_receipt(workspace, q, observations, scope["source"], complete, page["captured_at"], page.get("intake_ids")))
        public.update(r["source_record_id"] for r in complete)
        pointers.update({r["source_record_id"]: r for r in missing})
        pointer_times.update({r["source_record_id"]: page["captured_at"] for r in missing})
        nonpublic.extend(unlisted)
        normalization_pages.append((page, response, parsed))
        exhausted = parsed["exhausted"] is True and scope["provider"] in _BOARD_PROVIDERS
        expected_cursor = parsed["next_cursor"]
        accepted += 1
    for record_id, resolution in scope.get("resolutions", {}).items():
        record = _read_snapshot(workspace, resolution)
        if record_id not in pointers or record["source_record_id"] != record_id or record["source"] != scope["source"]:
            raise ValueError("retrieval_pointer_resolution_mismatch")
        if (queue._time(resolution["captured_at"]) < queue._time(pointer_times[record_id])
                or queue._time(resolution["captured_at"]) > current):
            raise ValueError("retrieval_capture_time_invalid")
        prepared = queue._intake(record)
        _pointer_identity(pointers[record_id], prepared)
        if resolution.get("status") not in {"captured", "ingested"}:
            raise ValueError("retrieval_pointer_resolution_invalid")
        if resolution["status"] == "captured":
            pending.append({"reason": "pointer_ingestion_interrupted", "next_action": "Replay the saved pointer resolution.", "source_record_id": record_id})
            continue
        receipts.append(_check_receipt(workspace, q, observations, scope["source"], [prepared], resolution["captured_at"], resolution.get("intake_ids")))
        public.add(record_id)
        del pointers[record_id]
    for page, response, parsed in normalization_pages:
        records = _normalization_records(scope, page, response, parsed)
        receipt = _audit_normalization(workspace, scope, page, records, current=current,
                                       q=q, observations=observations)
        if receipt is not None:
            receipts.append(receipt)
            for record in records:
                public.add(record["source_record_id"])
                pointers.pop(record["source_record_id"], None)
        elif records:
            ids = sorted(record["source_record_id"] for record in records)
            repairable.update(ids)
            conflicts = _normalization_conflicts(workspace, page, records, q, current=current,
                                                  original_records=_partition(scope, parsed["records"])[0])
            if conflicts:
                pending.append({"reason": "normalization_repair_conflicts_newer_observation", "snapshot": page["snapshot"],
                                "source_record_ids": sorted(conflicts),
                                "next_action": "Review the saved native description against newer posting evidence before reconciling this page."})
            else:
                pending.append({"reason": "normalization_replay_required", "snapshot": page["snapshot"],
                                "source_record_ids": ids,
                                "next_action": "Replay the saved response to ingest the complete normalized descriptions."})
    if not exhausted:
        reason = {"indeed": "provider_has_no_pagination", "unstructured": "unstructured_source_not_enumerable"}.get(scope["provider"], "retrieval_not_exhausted")
        action = {"indeed": "Use an independently registered complete board scope; this supplementary scope remains incomplete.",
                  "unstructured": "Extract every visible listing and pointer from the saved native response, then use an independently registered complete board scope."}.get(
                      scope["provider"], "Fetch the next provider page or retry the saved failure.")
        pending.append({"reason": reason, "next_action": action, "cursor": expected_cursor})
    if total is not None and scope["provider"] in _BOARD_PROVIDERS and exhausted and len(returned) != total:
        raise ValueError("retrieval_returned_total_mismatch")
    for record_id in pointers:
        if record_id in repairable:
            continue
        pending.append({"reason": "description_or_identity_missing", "source_record_id": record_id,
                        "next_action": "Fetch the full official description and explicitly resolve this pointer."})
    intake_snapshots = {digest for receipt in receipts
                        for digest in q["intake_batches"][receipt]["snapshot_hashes"]}
    for row in q["items"].values():
        conflict = row.get("capture_time_conflict")
        if (row["source"] == scope["source"] and conflict
                and intake_snapshots.intersection(conflict["snapshot_hashes"])):
            pending.append({"reason": "capture_time_conflict", "review_id": row["review_id"],
                            "captured_at": conflict["captured_at"], "posting_url": row["posting_url"],
                            "next_action": "Register a new scope for the same posting source and capture fresh evidence with a strictly later timestamp; then review the reopened posting."})
    pending.extend(_active_failures(scope))
    return {**scope, "complete": not pending, "status": "incomplete" if pending else "complete",
            "exhausted": exhausted, "next_cursor": expected_cursor, "reported_total": total,
            "returned_record_ids": sorted(returned), "source_record_ids": sorted(public),
            "known_returned_record_ids": sorted(returned | invalid_ids),
            "returned_records": len(returned | invalid_ids), "ingested_records": len(public),
            "returned_count_known": bool(accepted) and not unresolved_invalid and scope["provider"] != "unstructured",
            "intake_ids": sorted(set(receipts)), "unresolved_pointers": list(pointers.values()),
            "non_public_dispositions": nonpublic, "pending": pending}


def _refresh(workspace, ledger, scope, now):
    audited = _audit(workspace, scope, now=now)
    scope.update(audited)
    _save(workspace, ledger)
    return scope


def register_scope(workspace, *, run_id, source, provider, query, now):
    queue._time(now)
    if (not isinstance(run_id, str) or not run_id.strip() or not isinstance(source, str)
            or not source.strip() or provider not in _PROVIDERS or not isinstance(query, dict)):
        raise ValueError("retrieval_scope_invalid")
    _source_provider(source, provider)
    if provider in _BOARD_PROVIDERS:
        validate_board_query(provider, query)
    identity = {"run_id": run_id, "source": source, "provider": provider, "query": query}
    key = "scope:" + queue._digest(identity)
    with workspace_lock(workspace):
        ledger = load_ledger(workspace)
        if key not in ledger["scopes"]:
            ledger["scopes"][key] = {**identity, "scope_id": key, "registered_at": now,
                "registration_order": 1 + max((s.get("registration_order", 0) for s in ledger["scopes"].values()), default=0),
                "pages": [], "resolutions": {}, "status": "incomplete", "next_cursor": None,
                "unresolved_pointers": [], "intake_ids": [], "source_record_ids": []}
            _save(workspace, ledger)
        return _refresh(workspace, ledger, ledger["scopes"][key], now)


def capture_response(workspace, scope_id, response, *, now, cursor=None):
    queue._time(now)
    with workspace_lock(workspace):
        ledger = load_ledger(workspace)
        scope = _scope(ledger, scope_id)
        ref = _snapshot(workspace, response)
        page = next((p for p in scope["pages"] if p["snapshot_hash"] == ref["snapshot_hash"] and p["cursor"] == cursor), None)
        replaying = page is not None
        if page is None:
            page = {**ref, "cursor": cursor, "captured_at": now, "status": "captured", "intake_ids": [],
                    "normalization_version": NORMALIZATION_VERSION}
            scope["pages"].append(page)
            _save(workspace, ledger)  # Response and replay instruction precede parsing and intake.
        elif page["status"] == "ingested":
            return {**_refresh(workspace, ledger, scope, now), "capture_status": "ingested"}
        try:
            parsed = _parse(scope, response, cursor, normalization_version=_page_version(page))
            previous = {**scope, "pages": [p for p in scope["pages"] if p is not page]}
            prior = _audit(workspace, previous, now=now)
            if prior["exhausted"] or prior["next_cursor"] != cursor:
                raise ValueError("retrieval_cursor_sequence_invalid")
            if set(prior["returned_record_ids"]) & {r["source_record_id"] for r in parsed["records"]}:
                raise ValueError("retrieval_duplicate_page_records")
            if (prior["reported_total"] is not None and parsed["reported_total"] is not None
                    and prior["reported_total"] != parsed["reported_total"]):
                raise ValueError("retrieval_reported_total_changed")
        except ValueError as exc:
            page.update(status="invalid", error=str(exc))
            _save(workspace, ledger)
            return {**_refresh(workspace, ledger, scope, now), "capture_status": "invalid"}
        prepared, _, _ = _partition(scope, parsed["records"])
        queue.ingest(workspace, prepared, now=page["captured_at"], source=scope["source"], replay=replaying)
        page.update(status="ingested", intake_ids=[queue._digest(_receipt(scope["source"], prepared, page["captured_at"]))])
        page.pop("error", None)
        _set_active_failures(scope, [failure for failure in _active_failures(scope)
            if failure.get("stage", "page") != "page" or failure.get("cursor") != cursor])
        _save(workspace, ledger)
        return {**_refresh(workspace, ledger, scope, now), "capture_status": "ingested"}


def record_failure(workspace, scope_id, *, now, reason, next_action, source_record_id=None):
    queue._time(now)
    if not isinstance(reason, str) or not reason.strip() or not isinstance(next_action, str) or not next_action.strip():
        raise ValueError("retrieval_failure_action_required")
    with workspace_lock(workspace):
        ledger = load_ledger(workspace)
        scope = _scope(ledger, scope_id)
        audited = _audit(workspace, scope, now=now)
        unresolved = [p["source_record_id"] for p in audited["unresolved_pointers"]]
        if source_record_id is not None and (not isinstance(source_record_id, str) or source_record_id not in unresolved):
            raise ValueError("retrieval_failure_pointer_unknown")
        pointer_ids = [source_record_id] if source_record_id is not None else unresolved if audited["exhausted"] else []
        failure = {"reason": reason, "next_action": next_action, "captured_at": now,
                   "stage": "pointer" if pointer_ids else "page", "pending_pointer_ids": pointer_ids,
                   "cursor": audited["next_cursor"]}
        scope.setdefault("failures", []).append(failure)
        _set_active_failures(scope, [*_active_failures(scope), failure])
        return _refresh(workspace, ledger, scope, now)


def _pointer_identity(pointer, record):
    for field in ("employer", "title", "location", "requisition_id", "posting_url"):
        original = pointer.get(field)
        if original:
            same = original == record.get(field) if field == "posting_url" else queue._normalize(original) == queue._normalize(record.get(field))
            if not same:
                raise ValueError("retrieval_pointer_identity_mismatch")


def resolve_pointer(workspace, scope_id, *, source_record_id, record, now):
    queue._time(now)
    with workspace_lock(workspace):
        ledger = load_ledger(workspace)
        scope = _scope(ledger, scope_id)
        audited = _audit(workspace, scope, now=now)
        pointer = next((r for r in audited["unresolved_pointers"] if r["source_record_id"] == source_record_id), None)
        existing = scope["resolutions"].get(source_record_id)
        identity = pointer if pointer is not None else _read_snapshot(workspace, existing) if existing else None
        if identity is not None:
            record = {**{key: identity.get(key) for key in ("location", "requisition_id")}, **record}
        prepared = queue._intake(record)
        if (prepared["source_record_id"] != source_record_id or prepared["source"] != scope["source"]):
            raise ValueError("retrieval_pointer_identity_mismatch")
        if pointer is not None:
            _pointer_identity(pointer, prepared)
        if existing:
            if _read_snapshot(workspace, existing) != prepared:
                raise ValueError("retrieval_pointer_resolution_conflict")
            if existing["status"] == "ingested":
                return audited
        elif source_record_id not in {r["source_record_id"] for r in audited["unresolved_pointers"]}:
            raise ValueError("retrieval_pointer_unknown")
        else:
            scope["resolutions"][source_record_id] = {**_snapshot(workspace, prepared), "captured_at": now, "status": "captured"}
            _save(workspace, ledger)
        resolution = scope["resolutions"][source_record_id]
        queue.ingest(workspace, [prepared], now=resolution["captured_at"], source=scope["source"], replay=existing is not None)
        resolution.update(status="ingested", intake_ids=[queue._digest(_receipt(scope["source"], [prepared], resolution["captured_at"]))])
        _set_active_failures(scope, [failure for failure in _active_failures(scope)
            if not (failure.get("stage") == "pointer" and all(
                scope["resolutions"].get(record_id, {}).get("status") == "ingested"
                for record_id in failure["pending_pointer_ids"]))])
        return _refresh(workspace, ledger, scope, now)


def replay_scope(workspace, scope_id, *, now):
    """Repair interrupted ingestion from saved evidence before making new requests."""
    queue._time(now)
    with workspace_lock(workspace):
        scope = _scope(load_ledger(workspace), scope_id)
        _audit(workspace, scope, now=now)  # Integrity errors must stop recovery.
        for page in scope["pages"]:
            if page["status"] == "captured":
                capture_response(workspace, scope_id, _read_snapshot(workspace, page), now=now, cursor=page["cursor"])
        scope = _scope(load_ledger(workspace), scope_id)
        for record_id, resolution in scope["resolutions"].items():
            if resolution["status"] == "captured":
                resolve_pointer(workspace, scope_id, source_record_id=record_id,
                    record=_read_snapshot(workspace, resolution), now=now)
        ledger = load_ledger(workspace)
        scope = _scope(ledger, scope_id)
        _audit(workspace, scope, now=now)
        for page in scope["pages"]:
            if page["status"] != "ingested" or _page_version(page) == NORMALIZATION_VERSION:
                continue
            response = _read_snapshot(workspace, page)
            original = _parse(scope, response, page["cursor"], normalization_version=_page_version(page))
            records = _normalization_records(scope, page, response, original)
            if not records:
                continue
            if _normalization_conflicts(workspace, page, records, queue.load_queue(workspace), current=queue._time(now),
                                        original_records=_partition(scope, original["records"])[0]):
                continue
            if "normalization_repair" not in page:
                page["normalization_repair"] = {
                    **_snapshot(workspace, _normalization_snapshot(page, records)),
                    "page_snapshot_hash": page["snapshot_hash"], "normalization_version": NORMALIZATION_VERSION,
                    "captured_at": now, "status": "captured", "intake_ids": [],
                }
                _save(workspace, ledger)  # Additive repair evidence precedes queue mutation.
            repair = page["normalization_repair"]
            if repair["status"] == "ingested":
                continue
            queue.ingest(workspace, records, now=repair["captured_at"], source=scope["source"])
            repair.update(status="ingested", intake_ids=[queue._digest(
                _receipt(scope["source"], records, repair["captured_at"]))])
            _save(workspace, ledger)
        audited = _audit(workspace, scope, now=now)
        _set_active_failures(scope, [failure for failure in _active_failures(scope)
            if not (failure.get("stage") == "pointer" and failure.get("pending_pointer_ids")
                    and set(failure["pending_pointer_ids"]) <= set(audited["source_record_ids"]))])
        return _refresh(workspace, ledger, scope, now)


def summary(workspace, *, now):
    queue._time(now)
    with workspace_lock(workspace):
        ledger = load_ledger(workspace)
        q = queue.load_queue(workspace)
        observations = _observations(q)
        scopes = []
        for scope in ledger["scopes"].values():
            try:
                scopes.append(_audit(workspace, scope, now=now, review_queue=q, observations=observations))
            except (ValueError, KeyError, TypeError) as exc:
                scopes.append({**scope, "complete": False, "status": "incomplete", "pending": [
                    {"reason": "retrieval_evidence_invalid", "detail": str(exc), "next_action": "Repair or recapture the invalid retrieval evidence."}]})
        config_path = workspace.state / "config.json"
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        enabled = config.get("enabled_sources", [])
        if not isinstance(enabled, list) or not all(isinstance(name, str) for name in enabled):
            raise ValueError("retrieval_enabled_sources_invalid")
        current_run = max(scopes, key=lambda s: s["registration_order"])["run_id"] if scopes else None
        current_scopes = [s for s in scopes if s["run_id"] == current_run]
        missing = sorted(name for name in set(enabled) if not any(
            s["source"] == name or s["provider"] == name or
            (name == "public_ats" and s["provider"] in _BOARD_PROVIDERS) for s in current_scopes))
        complete = bool(scopes) and not missing and all(s["complete"] for s in scopes)
        pending = [{**p, "scope_id": s["scope_id"]} for s in scopes for p in s["pending"]]
        pending.extend({"source": name, "scope_id": None, "reason": "enabled_source_not_registered",
            "next_action": "Register and retrieve every planned query for this enabled source in the current run."} for name in missing)
        return {"complete": complete, "status": "complete" if complete else "incomplete" if scopes else "unknown",
            "scopes": scopes, "pending": pending, "missing_enabled_sources": missing,
            "unresolved_pointers": [{**p, "scope_id": s["scope_id"]} for s in scopes for p in s.get("unresolved_pointers", [])],
            "returned_records": sum(s.get("returned_records", 0) for s in scopes),
            "returned_count_known": bool(scopes) and not missing and all(s.get("returned_count_known", False) for s in scopes),
            "ingested_records": sum(s.get("ingested_records", 0) for s in scopes)}


def validate_source_result(workspace, source, result, *, now):
    result = asdict(result) if is_dataclass(result) else result
    if not result.get("success"):
        return
    with workspace_lock(workspace):
        try:
            current, completed = queue._time(now), queue._time(result.get("completed_at"))
            if completed > current:
                raise ValueError("completion_time_invalid")
            ledger = load_ledger(workspace)
            relevant = [s for s in ledger["scopes"].values() if s["source"] == source or
                        (source == "public_ats" and s["provider"] in _BOARD_PROVIDERS)]
            if not relevant:
                raise ValueError("scope_evidence_required")
            latest_run = max(relevant, key=lambda s: s["registration_order"])["run_id"]
            selected = [s for s in relevant if s["run_id"] == latest_run]
            ids = result.get("coverage_scope_ids")
            if not isinstance(ids, (list, tuple)) or len(ids) != len(set(ids)) or set(ids) != {s["scope_id"] for s in selected}:
                raise ValueError("coverage_scope_mismatch")
            q = queue.load_queue(workspace)
            observations = _observations(q)
            audited = []
            for scope in relevant:
                row = _audit(workspace, scope, now=result["completed_at"], review_queue=q, observations=observations)
                if not row["complete"]:
                    raise ValueError("scope_incomplete")
                if scope["run_id"] == latest_run:
                    audited.append(row)
            expected_intakes = {i for s in audited for i in s["intake_ids"]}
            expected_records = {i for s in audited for i in s["source_record_ids"]}
            if set(result.get("intake_ids", ())) != expected_intakes or set(result.get("seen_records", ())) != expected_records:
                raise ValueError("intake_records_mismatch")
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("retrieval_incomplete:" + source + ":" + str(exc)) from exc
