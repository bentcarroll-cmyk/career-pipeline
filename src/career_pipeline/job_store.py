"""Canonical local job folders, monotonic IDs, and locked status updates."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Iterator, Mapping

from .atomic import atomic_write_json, atomic_write_text, load_json
from .contracts import WorkspacePaths
from .dedupe import candidate_key, fallback_identity, requisition_identity
from .evaluation import JobAssessment
from .schema import validate_document
from .sources.base import CandidateJob


class JobStoreError(ValueError):
    pass


class WorkspaceLockedError(JobStoreError):
    pass


class DuplicateJobError(JobStoreError):
    def __init__(self, job_ids: tuple[str, ...]):
        super().__init__("candidate already exists in the canonical job store")
        self.job_ids = job_ids


_JOB_ID = re.compile(r"JOB-[0-9]{6}")
_STATUSES = {
    "new",
    "needs_confirmation",
    "prepare_application",
    "packet_ready",
    "applied",
    "interviewing",
    "offer",
    "not_pursuing",
    "closed",
}


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def workspace_lock(workspace: WorkspacePaths) -> Iterator[None]:
    lock_path = workspace.state / ".workspace.lock"
    try:
        descriptor = os.open(
            str(lock_path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError as exc:
        raise WorkspaceLockedError("workspace mutation is already in progress") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("locked\n")
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(workspace.state)
        yield
    finally:
        lock_path.unlink(missing_ok=True)
        _fsync_directory(workspace.state)


def _allocate_job_id_locked(workspace: WorkspacePaths) -> str:
    counter_path = workspace.state / "next-job-id.json"
    try:
        counter = load_json(counter_path)
        next_id = counter["next_id"]
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        raise JobStoreError("next job ID state is invalid") from exc
    if (
        counter.get("schema_version") != 1
        or not isinstance(next_id, int)
        or isinstance(next_id, bool)
        or not 1 <= next_id <= 999999
    ):
        raise JobStoreError("next job ID state is invalid")
    atomic_write_json(
        counter_path,
        {"schema_version": 1, "next_id": next_id + 1},
    )
    return f"JOB-{next_id:06d}"


def allocate_job_id(workspace: WorkspacePaths) -> str:
    with workspace_lock(workspace):
        return _allocate_job_id_locked(workspace)


def _job_paths(job_id: str) -> dict[str, str]:
    base = f"Jobs/{job_id}"
    return {
        "posting": f"{base}/posting.md",
        "assessment": f"{base}/assessment.md",
        "events": f"{base}/events.jsonl",
        "working": f"{base}/working",
    }


def _build_record(
    job_id: str,
    candidate: CandidateJob,
    assessment: JobAssessment,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "job_id": job_id,
        "source_record_id": candidate.source_record_id,
        "employer": candidate.employer,
        "title": candidate.title,
        "location": candidate.location,
        "workplace_model": candidate.workplace_model,
        "travel": candidate.travel,
        "compensation_evidence": candidate.compensation_evidence,
        "posting_url": candidate.posting_url,
        "application_url": candidate.application_url,
        "requisition_id": candidate.requisition_id,
        "team": candidate.team,
        "posted_at": candidate.posted_at,
        "updated_at": candidate.updated_at,
        "source": candidate.source,
        "verified_at": candidate.verified_at,
        "verification_status": candidate.verification_status,
        "raw_field_hash": candidate.raw_field_hash,
        "disposition": assessment.disposition,
        "status": "new",
        "role_to_profile_fit": assessment.role_to_profile_fit,
        "strengths": [asdict(strength) for strength in assessment.strengths],
        "gaps": list(assessment.gaps),
        "uncertainties": list(assessment.uncertainties),
        "deadline": candidate.deadline,
        "recommended_next_action": (
            "Review this verified role and decide whether to request an application packet."
        ),
        "discovered_at": candidate.verified_at,
        "reverified_at": None,
        "paths": _job_paths(job_id),
        "application_versions": [],
        "exports": [],
    }


def _event(
    job_id: str,
    event_type: str,
    occurred_at: str,
    *,
    prior_status: str | None,
    status: str,
    metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "job_id": job_id,
        "prior_status": prior_status,
        "status": status,
        "metadata": dict(metadata or {}),
    }


def _write_job_files(
    temp_dir: Path,
    record: Mapping[str, object],
    posting_markdown: str,
    assessment_markdown: str,
    creation_event: Mapping[str, object],
) -> None:
    if not posting_markdown.strip() or not assessment_markdown.strip():
        raise JobStoreError("posting and assessment evidence must be non-empty")
    (temp_dir / "working").mkdir()
    atomic_write_json(temp_dir / "job.json", record)
    atomic_write_text(temp_dir / "posting.md", posting_markdown)
    atomic_write_text(temp_dir / "assessment.md", assessment_markdown)
    atomic_write_text(
        temp_dir / "events.jsonl",
        json.dumps(creation_event, sort_keys=True, separators=(",", ":")) + "\n",
    )
    for path in temp_dir.iterdir():
        if path.is_file():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
    _fsync_directory(temp_dir / "working")
    _fsync_directory(temp_dir)


def create_job(
    workspace: WorkspacePaths,
    candidate: CandidateJob,
    assessment: JobAssessment,
    *,
    posting_markdown: str,
    assessment_markdown: str,
    occurred_at: str,
) -> dict[str, object]:
    if assessment.disposition not in {"strong_match", "worth_considering"}:
        raise JobStoreError("only qualifying roles receive canonical job folders")
    if not occurred_at:
        raise JobStoreError("occurred_at is required")
    temp_dir: Path | None = None
    with workspace_lock(workspace):
        duplicates = _duplicate_job_ids_locked(workspace, candidate)
        if duplicates:
            raise DuplicateJobError(duplicates)
        job_id = _allocate_job_id_locked(workspace)
        final_dir = workspace.jobs / job_id
        if final_dir.exists():
            raise JobStoreError("allocated job folder already exists")
        record = _build_record(job_id, candidate, assessment)
        errors = validate_document("job", record)
        if errors:
            raise JobStoreError(f"canonical job is invalid: {errors[0].code}")
        temp_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{job_id}.",
                suffix=".tmp",
                dir=str(workspace.jobs),
            )
        )
        try:
            _write_job_files(
                temp_dir,
                record,
                posting_markdown,
                assessment_markdown,
                _event(
                    job_id,
                    "job_created",
                    occurred_at,
                    prior_status=None,
                    status="new",
                ),
            )
            os.replace(temp_dir, final_dir)
            temp_dir = None
            _fsync_directory(workspace.jobs)
            return read_job(workspace, job_id)
        finally:
            if temp_dir is not None and temp_dir.exists():
                shutil.rmtree(temp_dir)


def _duplicate_job_ids_locked(
    workspace: WorkspacePaths,
    candidate: CandidateJob,
) -> tuple[str, ...]:
    wanted = candidate_key(candidate)
    duplicates: list[str] = []
    for job_dir in sorted(workspace.jobs.iterdir(), key=lambda path: path.name):
        if not job_dir.is_dir() or _JOB_ID.fullmatch(job_dir.name) is None:
            continue
        record = read_job(workspace, job_dir.name)
        if candidate.requisition_id:
            existing = requisition_identity(
                str(record["employer"]),
                str(record["requisition_id"])
                if record.get("requisition_id")
                else None,
            )
        else:
            existing = fallback_identity(
                str(record["employer"]),
                str(record["title"]),
                str(record["location"]) if record.get("location") else None,
                str(record["team"]) if record.get("team") else None,
            )
        if existing == wanted:
            duplicates.append(job_dir.name)
    return tuple(duplicates)


def _canonical_job_dir(workspace: WorkspacePaths, job_id: str) -> Path:
    if _JOB_ID.fullmatch(job_id) is None:
        raise JobStoreError("job ID must match JOB-000000")
    job_dir = workspace.jobs / job_id
    try:
        if job_dir.resolve().parent != workspace.jobs.resolve():
            raise JobStoreError("job path escapes the canonical store")
    except FileNotFoundError as exc:
        raise JobStoreError("canonical job does not exist") from exc
    return job_dir


def read_job(workspace: WorkspacePaths, job_id: str) -> dict[str, object]:
    job_dir = _canonical_job_dir(workspace, job_id)
    try:
        record = load_json(job_dir / "job.json")
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        raise JobStoreError("canonical job record is unreadable") from exc
    if record.get("job_id") != job_id:
        raise JobStoreError("canonical job ID does not match its folder")
    errors = validate_document("job", record)
    if errors:
        raise JobStoreError(f"canonical job is invalid: {errors[0].code}")
    for name in ("posting.md", "assessment.md", "events.jsonl"):
        if not (job_dir / name).is_file():
            raise JobStoreError(f"canonical job is missing {name}")
    if not (job_dir / "working").is_dir():
        raise JobStoreError("canonical job is missing working")
    return record


def update_job_status(
    workspace: WorkspacePaths,
    job_id: str,
    status: str,
    *,
    occurred_at: str,
    metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if status not in _STATUSES:
        raise JobStoreError("unsupported job status")
    if not occurred_at:
        raise JobStoreError("occurred_at is required")
    with workspace_lock(workspace):
        current = read_job(workspace, job_id)
        prior_status = str(current["status"])
        if prior_status == status:
            return current
        updated = dict(current)
        updated["status"] = status
        errors = validate_document("job", updated)
        if errors:
            raise JobStoreError(f"updated job is invalid: {errors[0].code}")
        job_dir = workspace.jobs / job_id
        events_path = job_dir / "events.jsonl"
        prior_events = events_path.read_text(encoding="utf-8")
        event_line = json.dumps(
            _event(
                job_id,
                "status_changed",
                occurred_at,
                prior_status=prior_status,
                status=status,
                metadata=metadata,
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
        atomic_write_json(job_dir / "job.json", updated)
        atomic_write_text(events_path, prior_events + event_line + "\n")
        return read_job(workspace, job_id)
