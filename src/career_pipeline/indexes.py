"""Disposable backlog and duplicate indexes derived from canonical job folders."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping

from .atomic import atomic_write_json, load_json
from .contracts import WorkspacePaths
from .dedupe import (
    OpportunityIdentity,
    candidate_identity,
    identity_from_fields,
    resolve_identity,
)
from .job_store import JobStoreError, read_job, workspace_lock_if_needed
from .sources.base import CandidateJob


@dataclass(frozen=True)
class IndexBundle:
    backlog: Mapping[str, object]
    deduplication: Mapping[str, object]


_JOB_DIR = re.compile(r"JOB-[0-9]{6}")


def _canonical_records(
    workspace: WorkspacePaths,
) -> tuple[tuple[dict[str, object], str], ...]:
    records: list[tuple[dict[str, object], str]] = []
    for job_dir in sorted(workspace.jobs.iterdir(), key=lambda path: path.name):
        if not job_dir.is_dir() or _JOB_DIR.fullmatch(job_dir.name) is None:
            continue
        record = read_job(workspace, job_dir.name)
        record_hash = hashlib.sha256((job_dir / "job.json").read_bytes()).hexdigest()
        records.append((record, record_hash))
    return tuple(records)


def _source_hash(records: tuple[tuple[dict[str, object], str], ...]) -> str:
    digest = hashlib.sha256()
    for record, record_hash in records:
        digest.update(str(record["job_id"]).encode("utf-8"))
        digest.update(b"\x00")
        digest.update(record_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _backlog_summary(record: Mapping[str, object], record_hash: str) -> dict[str, object]:
    return {
        "job_id": record["job_id"],
        "employer": record["employer"],
        "title": record["title"],
        "location": record.get("location"),
        "workplace_model": record.get("workplace_model"),
        "disposition": record["disposition"],
        "status": record["status"],
        "deadline": record.get("deadline"),
        "recommended_next_action": record["recommended_next_action"],
        "record_hash": record_hash,
    }


def _identity_keys(record: Mapping[str, object]) -> tuple[str, ...]:
    identity = identity_from_fields(
        str(record["employer"]),
        str(record["requisition_id"]) if record.get("requisition_id") else None,
        str(record["title"]),
        str(record["location"]) if record.get("location") else None,
        str(record["team"]) if record.get("team") else None,
    )
    return (
        (identity.requisition, identity.fallback)
        if identity.requisition
        else (identity.fallback,)
    )


def _build_indexes(workspace: WorkspacePaths) -> IndexBundle:
    records = _canonical_records(workspace)
    source_hash = _source_hash(records)
    identities: dict[str, list[str]] = {}
    record_hashes: dict[str, str] = {}
    identity_records: dict[str, dict[str, str | None]] = {}
    backlog_jobs: list[dict[str, object]] = []
    for record, record_hash in records:
        job_id = str(record["job_id"])
        record_hashes[job_id] = record_hash
        identity = identity_from_fields(
            str(record["employer"]),
            str(record["requisition_id"]) if record.get("requisition_id") else None,
            str(record["title"]),
            str(record["location"]) if record.get("location") else None,
            str(record["team"]) if record.get("team") else None,
        )
        identity_records[job_id] = {
            "requisition": identity.requisition,
            "fallback": identity.fallback,
        }
        backlog_jobs.append(_backlog_summary(record, record_hash))
        for key in _identity_keys(record):
            identities.setdefault(key, []).append(job_id)
    return IndexBundle(
        backlog={
            "schema_version": 1,
            "source_hash": source_hash,
            "jobs": backlog_jobs,
        },
        deduplication={
            "schema_version": 1,
            "source_hash": source_hash,
            "record_hashes": record_hashes,
            "identity_records": identity_records,
            "identities": {key: value for key, value in sorted(identities.items())},
        },
    )


def _write_indexes(workspace: WorkspacePaths, indexes: IndexBundle) -> None:
    atomic_write_json(workspace.indexes / "backlog.json", indexes.backlog)
    atomic_write_json(
        workspace.indexes / "deduplication.json",
        indexes.deduplication,
    )


def rebuild_indexes(workspace: WorkspacePaths) -> IndexBundle:
    with workspace_lock_if_needed(workspace):
        indexes = _build_indexes(workspace)
        _write_indexes(workspace, indexes)
        return indexes


def load_indexes(workspace: WorkspacePaths) -> IndexBundle:
    with workspace_lock_if_needed(workspace):
        expected = _build_indexes(workspace)
        try:
            current = IndexBundle(
                backlog=load_json(workspace.indexes / "backlog.json"),
                deduplication=load_json(workspace.indexes / "deduplication.json"),
            )
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            current = None
        if current != expected:
            _write_indexes(workspace, expected)
            return expected
        return current


def duplicate_job_ids(
    indexes: IndexBundle,
    identity: str,
) -> tuple[str, ...]:
    identities = indexes.deduplication.get("identities")
    if not isinstance(identities, Mapping):
        raise JobStoreError("deduplication index is invalid")
    value = identities.get(identity, ())
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise JobStoreError("deduplication identity is invalid")
    return tuple(value)


def resolve_duplicate_job_ids(
    indexes: IndexBundle,
    candidate: CandidateJob,
) -> tuple[tuple[str, ...], bool]:
    raw = indexes.deduplication.get("identity_records")
    if not isinstance(raw, Mapping):
        raise JobStoreError("deduplication identity records are invalid")
    existing: dict[str, OpportunityIdentity] = {}
    for job_id, value in raw.items():
        if (
            not isinstance(job_id, str)
            or not isinstance(value, Mapping)
            or not isinstance(value.get("fallback"), str)
            or (
                value.get("requisition") is not None
                and not isinstance(value.get("requisition"), str)
            )
        ):
            raise JobStoreError("deduplication identity record is invalid")
        existing[job_id] = OpportunityIdentity(
            value.get("requisition"), str(value["fallback"])
        )
    resolution = resolve_identity(candidate_identity(candidate), existing)
    return (
        resolution.matched_ids or resolution.ambiguous_ids,
        resolution.ambiguous,
    )
