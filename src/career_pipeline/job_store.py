"""Canonical local job folders, monotonic IDs, and locked status updates."""

from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator, Mapping

from .atomic import atomic_write_json, atomic_write_text, load_json
from .contracts import WorkspacePaths
from .dedupe import candidate_key, fallback_identity, requisition_identity
from .evaluation import JobAssessment
from .schema import validate_document
from .sources.base import CandidateJob
from .timestamps import TimestampError, parse_instant


class JobStoreError(ValueError):
    pass


class WorkspaceLockedError(JobStoreError):
    pass


class DuplicateJobError(JobStoreError):
    def __init__(self, job_ids: tuple[str, ...]):
        super().__init__("candidate already exists in the canonical job store")
        self.job_ids = job_ids


@dataclass(frozen=True)
class ReverificationResult:
    record: Mapping[str, object]
    changed_fields: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.changed_fields)


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
_HELD_LOCKS: set[Path] = set()
_PENDING_MUTATION = "pending-mutation.json"
_PRE_APPLICATION_STATUSES = frozenset(
    {"new", "needs_confirmation", "prepare_application", "packet_ready"}
)
_SOURCE_PRIORITY = {
    "public-search": 10,
    "browser": 10,
    "firecrawl": 10,
    "indeed": 20,
    "linkedin": 20,
    "public_ats": 30,
    "greenhouse": 30,
    "lever": 30,
    "ashby": 30,
    "usajobs": 30,
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
    resolved_lock = lock_path.resolve()
    if resolved_lock in _HELD_LOCKS:
        raise WorkspaceLockedError("workspace mutation is already in progress")
    descriptor = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(descriptor)
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            raise WorkspaceLockedError("workspace mutation is already in progress") from exc
        raise
    _HELD_LOCKS.add(resolved_lock)
    try:
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        _fsync_directory(workspace.state)
        _recover_all_pending_mutations_locked(workspace)
        yield
    finally:
        _HELD_LOCKS.discard(resolved_lock)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


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
    if (job_dir / "working" / _PENDING_MUTATION).exists():
        raise JobStoreError("canonical job has a pending mutation")
    return _read_valid_job(job_dir, job_id)


def _read_valid_job(job_dir: Path, job_id: str) -> dict[str, object]:
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


def _recover_pending_mutation_locked(
    workspace: WorkspacePaths,
    job_id: str,
) -> None:
    job_dir = _canonical_job_dir(workspace, job_id)
    pending_path = job_dir / "working" / _PENDING_MUTATION
    if not pending_path.exists():
        return
    try:
        journal = load_json(pending_path)
        updated = journal["updated_job"]
        event = journal["event"]
        file_updates = journal.get("file_updates", {})
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise JobStoreError("pending canonical mutation is unreadable") from exc
    if (
        journal.get("schema_version") != 1
        or journal.get("job_id") != job_id
        or not isinstance(updated, Mapping)
        or not isinstance(event, Mapping)
        or not isinstance(file_updates, Mapping)
        or updated.get("job_id") != job_id
        or event.get("job_id") != job_id
    ):
        raise JobStoreError("pending canonical mutation is invalid")
    if (
        event.get("schema_version") != 1
        or not isinstance(event.get("event_type"), str)
        or not isinstance(event.get("occurred_at"), str)
        or event.get("status") not in _STATUSES
        or not isinstance(event.get("metadata"), Mapping)
        or not set(file_updates).issubset({"posting.md", "assessment.md"})
        or not all(
            isinstance(value, str) and value.strip()
            for value in file_updates.values()
        )
    ):
        raise JobStoreError("pending canonical mutation is invalid")
    errors = validate_document("job", updated)
    if errors:
        raise JobStoreError(f"pending canonical job is invalid: {errors[0].code}")
    event_line = json.dumps(event, sort_keys=True, separators=(",", ":"))
    events_path = job_dir / "events.jsonl"
    prior_events = events_path.read_text(encoding="utf-8")
    if event_line not in prior_events.splitlines():
        atomic_write_text(events_path, prior_events + event_line + "\n")
    for name, value in sorted(file_updates.items()):
        atomic_write_text(job_dir / name, value)
    atomic_write_json(job_dir / "job.json", dict(updated))
    pending_path.unlink()
    _fsync_directory(pending_path.parent)


def _recover_all_pending_mutations_locked(workspace: WorkspacePaths) -> None:
    if not workspace.jobs.is_dir():
        return
    for job_dir in sorted(workspace.jobs.iterdir(), key=lambda path: path.name):
        if job_dir.is_dir() and _JOB_ID.fullmatch(job_dir.name):
            _recover_pending_mutation_locked(workspace, job_dir.name)


def _commit_job_mutation_locked(
    workspace: WorkspacePaths,
    job_id: str,
    updated: Mapping[str, object],
    event: Mapping[str, object],
    file_updates: Mapping[str, str] | None = None,
) -> None:
    pending_path = workspace.jobs / job_id / "working" / _PENDING_MUTATION
    atomic_write_json(
        pending_path,
        {
            "schema_version": 1,
            "job_id": job_id,
            "updated_job": dict(updated),
            "event": dict(event),
            "file_updates": dict(file_updates or {}),
        },
    )
    _recover_pending_mutation_locked(workspace, job_id)


def reverify_job(
    workspace: WorkspacePaths,
    job_id: str,
    candidate: CandidateJob,
    assessment: JobAssessment,
    *,
    posting_markdown: str,
    assessment_markdown: str,
    occurred_at: str,
) -> ReverificationResult:
    if assessment.disposition not in {"strong_match", "worth_considering"}:
        raise JobStoreError("only qualifying roles can update a canonical job")
    if not occurred_at:
        raise JobStoreError("occurred_at is required")
    with workspace_lock(workspace):
        current = read_job(workspace, job_id)
        current_identity = (
            requisition_identity(
                str(current["employer"]),
                str(current["requisition_id"]),
            )
            if current.get("requisition_id")
            else fallback_identity(
                str(current["employer"]),
                str(current["title"]),
                str(current["location"]) if current.get("location") else None,
                str(current["team"]) if current.get("team") else None,
            )
        )
        if candidate_key(candidate) != current_identity:
            raise JobStoreError("reverification identity does not match canonical job")
        try:
            current_verified_at = parse_instant(str(current["verified_at"]))
            candidate_verified_at = parse_instant(candidate.verified_at)
            occurred_instant = parse_instant(occurred_at)
            prior_reverified_at = current.get("reverified_at")
            prior_reverified_instant = (
                parse_instant(str(prior_reverified_at))
                if prior_reverified_at is not None
                else None
            )
        except TimestampError as exc:
            raise JobStoreError(
                "reverification timestamps must be timezone-aware ISO 8601"
            ) from exc
        same_source = current.get("source") == candidate.source
        same_content = current.get("raw_field_hash") == candidate.raw_field_hash
        evidence_is_current = candidate_verified_at >= current_verified_at
        exact_requisition = bool(
            current.get("requisition_id")
            and candidate.requisition_id
            and requisition_identity(
                str(current["employer"]),
                str(current["requisition_id"]),
            )
            == requisition_identity(candidate.employer, candidate.requisition_id)
        )
        stronger_source = _SOURCE_PRIORITY.get(candidate.source, 0) > _SOURCE_PRIORITY.get(
            str(current.get("source", "")), 0
        )
        replace_evidence = evidence_is_current and (
            (same_source and not same_content)
            or (not same_source and exact_requisition and stronger_source)
        )
        if replace_evidence:
            updated = _build_record(job_id, candidate, assessment)
            for field in (
                "status",
                "discovered_at",
                "paths",
                "application_versions",
                "exports",
            ):
                updated[field] = current[field]
            file_updates = {
                "posting.md": posting_markdown,
                "assessment.md": assessment_markdown,
            }
        else:
            updated = dict(current)
            file_updates = None
            if same_source and same_content and evidence_is_current:
                updated["verified_at"] = candidate.verified_at
        updated["reverified_at"] = (
            str(prior_reverified_at)
            if prior_reverified_instant is not None
            and prior_reverified_instant > occurred_instant
            else occurred_at
        )
        changed_fields = tuple(
            sorted(
                field
                for field, value in updated.items()
                if field not in {"reverified_at", "verified_at"}
                and current.get(field) != value
            )
        )
        errors = validate_document("job", updated)
        if errors:
            raise JobStoreError(f"reverified job is invalid: {errors[0].code}")
        event = _event(
            job_id,
            "job_reverified",
            occurred_at,
            prior_status=str(current["status"]),
            status=str(current["status"]),
            metadata={
                "changed_fields": list(changed_fields),
                "verification_source": candidate.source,
                "stale_evidence_ignored": not evidence_is_current,
            },
        )
        _commit_job_mutation_locked(
            workspace,
            job_id,
            updated,
            event,
            file_updates,
        )
        return ReverificationResult(read_job(workspace, job_id), changed_fields)


def update_job_status(
    workspace: WorkspacePaths,
    job_id: str,
    status: str,
    *,
    occurred_at: str,
    metadata: Mapping[str, object] | None = None,
    allowed_prior_statuses: frozenset[str] | None = None,
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
        if (
            allowed_prior_statuses is not None
            and prior_status not in allowed_prior_statuses
        ):
            return current
        updated = dict(current)
        updated["status"] = status
        errors = validate_document("job", updated)
        if errors:
            raise JobStoreError(f"updated job is invalid: {errors[0].code}")
        event = _event(
            job_id,
            "status_changed",
            occurred_at,
            prior_status=prior_status,
            status=status,
            metadata=metadata,
        )
        _commit_job_mutation_locked(workspace, job_id, updated, event)
        return read_job(workspace, job_id)


def record_application_version(
    workspace: WorkspacePaths,
    job_id: str,
    version: Mapping[str, object],
    *,
    occurred_at: str,
) -> dict[str, object]:
    required = ("version", "resume_pdf", "artifact_hashes")
    if any(not version.get(field) for field in required):
        raise JobStoreError("application version receipt is incomplete")
    if not isinstance(version.get("artifact_hashes"), Mapping):
        raise JobStoreError("application artifact hashes are invalid")
    if re.fullmatch(r"v[0-9]{3}", str(version["version"])) is None:
        raise JobStoreError("application version is invalid")
    if any(
        not isinstance(value, str)
        or re.fullmatch(r"[a-f0-9]{64}", value) is None
        for value in version["artifact_hashes"].values()
    ):
        raise JobStoreError("application artifact hashes are invalid")
    for field in ("resume_pdf", "cover_letter_pdf"):
        value = version.get(field)
        if value is None and field == "cover_letter_pdf":
            continue
        if not isinstance(value, str) or not value:
            raise JobStoreError("application artifact path is invalid")
        parsed = PurePosixPath(value)
        if (
            parsed.is_absolute()
            or ".." in parsed.parts
            or len(parsed.parts) < 3
            or parsed.parts[0] != "Applications"
            or not parsed.parts[1].startswith(f"{job_id}_")
        ):
            raise JobStoreError("application artifact path is outside the job packet")
    with workspace_lock(workspace):
        current = read_job(workspace, job_id)
        versions = list(current.get("application_versions", ()))
        if not all(isinstance(item, Mapping) for item in versions):
            raise JobStoreError("canonical application history is invalid")
        same_number = [
            item for item in versions if item.get("version") == version["version"]
        ]
        if same_number and same_number[0] != dict(version):
            raise JobStoreError("application version conflicts with canonical history")
        if not same_number:
            versions.append(dict(version))
        if same_number:
            return current
        updated = dict(current)
        updated["application_versions"] = versions
        prior_status = str(current["status"])
        status = (
            "packet_ready"
            if prior_status in _PRE_APPLICATION_STATUSES
            else prior_status
        )
        updated["status"] = status
        errors = validate_document("job", updated)
        if errors:
            raise JobStoreError(f"updated job is invalid: {errors[0].code}")
        event = _event(
            job_id,
            "packet_ready" if status == "packet_ready" else "application_version_recorded",
            occurred_at,
            prior_status=prior_status,
            status=status,
            metadata={"version": version["version"]},
        )
        _commit_job_mutation_locked(workspace, job_id, updated, event)
        return read_job(workspace, job_id)


def record_export_receipt(
    workspace: WorkspacePaths,
    job_id: str,
    receipt: Mapping[str, object],
) -> dict[str, object]:
    required_strings = (
        "destination_kind",
        "destination_id",
        "exported_at",
        "content_hash",
    )
    if any(not isinstance(receipt.get(field), str) or not receipt.get(field) for field in required_strings):
        raise JobStoreError("export receipt is incomplete")
    if receipt.get("verified") is not True:
        raise JobStoreError("export receipt is not verified")
    content_hash = str(receipt["content_hash"])
    if re.fullmatch(r"[a-f0-9]{64}", content_hash) is None:
        raise JobStoreError("export content hash is invalid")
    artifact_hashes = receipt.get("artifact_hashes")
    if not isinstance(artifact_hashes, Mapping) or any(
        not isinstance(value, str)
        or re.fullmatch(r"[a-f0-9]{64}", value) is None
        for value in artifact_hashes.values()
    ):
        raise JobStoreError("export artifact hashes are invalid")
    with workspace_lock(workspace):
        current = read_job(workspace, job_id)
        exports = list(current.get("exports", ()))
        if not all(isinstance(item, Mapping) for item in exports):
            raise JobStoreError("canonical export history is invalid")
        same_content = [
            item
            for item in exports
            if item.get("destination_kind") == receipt["destination_kind"]
            and item.get("content_hash") == content_hash
        ]
        if same_content:
            return current
        exports.append(dict(receipt))
        updated = dict(current)
        updated["exports"] = exports
        errors = validate_document("job", updated)
        if errors:
            raise JobStoreError(f"updated job is invalid: {errors[0].code}")
        event = _event(
            job_id,
            "export_verified",
            str(receipt["exported_at"]),
            prior_status=str(current["status"]),
            status=str(current["status"]),
            metadata={
                "destination_kind": receipt["destination_kind"],
                "content_hash": content_hash,
            },
        )
        _commit_job_mutation_locked(workspace, job_id, updated, event)
        return read_job(workspace, job_id)
