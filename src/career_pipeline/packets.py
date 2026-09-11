"""Immediate, versioned application packets delivered to the local workspace."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Mapping

from .atomic import atomic_write_json, load_json
from .contracts import WorkspacePaths
from .indexes import load_indexes
from .job_store import (
    JobStoreError,
    read_job,
    record_application_version,
    update_job_status,
    workspace_lock,
)
from .quality import QualityReceipt, validate_quality_receipt


STAGES = (
    "selected",
    "posting_verified",
    "drafted",
    "quality_checked",
    "saved",
    "local_verified",
    "ready",
)


class InvalidPacketTransition(ValueError):
    pass


@dataclass(frozen=True)
class PacketOptions:
    cover_letter_enabled: bool = True
    profile_hash: str | None = None


@dataclass(frozen=True)
class PacketRecord:
    job_id: str
    employer: str
    title: str
    version: str
    version_dir: Path
    resume_pdf: Path
    cover_letter_pdf: Path | None
    working_dir: Path
    stage: str = "selected"
    receipts: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    profile_hash: str | None = None

    @property
    def ticket_id(self) -> str:
        return self.job_id


@dataclass(frozen=True)
class ApplicationManifest:
    schema_version: int = 1
    packets: Mapping[str, tuple[PacketRecord, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactVerification:
    valid: bool
    errors: tuple[str, ...]
    hashes: Mapping[str, str]


_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")
_UNDERSCORES = re.compile(r"_+")


def _safe_component(value: str) -> str:
    cleaned = _UNSAFE.sub("_", value.strip())
    cleaned = _UNDERSCORES.sub("_", cleaned).strip("_-")
    if not cleaned:
        raise ValueError("packet path component is empty after sanitization")
    if len(cleaned) <= 72:
        return cleaned
    suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned[:63].rstrip('_-')}_{suffix}"


def _latest(manifest: ApplicationManifest, job_id: str) -> PacketRecord | None:
    records = manifest.packets.get(job_id, ())
    return records[-1] if records else None


def _resolve(workspace: WorkspacePaths, relative: Path) -> Path:
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts:
        raise InvalidPacketTransition("packet path must be workspace-relative")
    resolved = (workspace.root / Path(*pure.parts)).resolve()
    try:
        resolved.relative_to(workspace.root.resolve())
    except ValueError as exc:
        raise InvalidPacketTransition("packet path escapes the workspace") from exc
    return resolved


def start_packet(
    workspace: WorkspacePaths,
    job_id: str,
    options: PacketOptions,
    manifest: ApplicationManifest,
    *,
    occurred_at: str,
    explicit_request: bool,
) -> tuple[ApplicationManifest, PacketRecord]:
    if not explicit_request:
        raise InvalidPacketTransition("packet preparation requires an explicit request")
    try:
        job = read_job(workspace, job_id)
    except JobStoreError as exc:
        raise InvalidPacketTransition("packet job must exist in the canonical store") from exc
    if not occurred_at:
        raise InvalidPacketTransition("occurred_at is required")
    update_job_status(
        workspace,
        job_id,
        "prepare_application",
        occurred_at=occurred_at,
    )
    current = _latest(manifest, job_id)
    if current is not None and current.stage != "ready":
        return manifest, current

    employer = _safe_component(str(job["employer"]))
    title = _safe_component(str(job["title"]))
    application_dir = Path("Applications") / f"{job_id}_{employer}_{title}"
    actual_application_dir = _resolve(workspace, application_dir)
    with workspace_lock(workspace):
        actual_application_dir.mkdir(parents=True, exist_ok=True)
        versions = [
            int(name[1:])
            for name in (path.name for path in actual_application_dir.iterdir())
            if re.fullmatch(r"v[0-9]{3}", name)
        ]
        number = max(versions, default=0) + 1
        version = f"v{number:03d}"
        version_dir = application_dir / version
        actual_version_dir = _resolve(workspace, version_dir)
        actual_version_dir.mkdir()
        working_dir = version_dir / "working"
        _resolve(workspace, working_dir).mkdir()

    resume_pdf = version_dir / f"Resume_{employer}_{title}.pdf"
    cover_letter_pdf = (
        version_dir / f"Cover_Letter_{employer}_{title}.pdf"
        if options.cover_letter_enabled
        else None
    )
    record = PacketRecord(
        job_id=job_id,
        employer=str(job["employer"]),
        title=str(job["title"]),
        version=version,
        version_dir=version_dir,
        resume_pdf=resume_pdf,
        cover_letter_pdf=cover_letter_pdf,
        working_dir=working_dir,
        profile_hash=options.profile_hash,
    )
    packets = dict(manifest.packets)
    packets[job_id] = (*packets.get(job_id, ()), record)
    return replace(manifest, packets=packets), record


def advance_packet(
    manifest: ApplicationManifest,
    job_id: str,
    stage: str,
    receipt: Mapping[str, object],
) -> ApplicationManifest:
    current = _latest(manifest, job_id)
    if current is None:
        raise InvalidPacketTransition("packet job is not in the manifest")
    if stage not in STAGES:
        raise InvalidPacketTransition(f"unknown packet stage: {stage}")
    current_index = STAGES.index(current.stage)
    requested_index = STAGES.index(stage)
    if requested_index == current_index:
        if dict(current.receipts.get(stage, {})) != dict(receipt):
            raise InvalidPacketTransition("repeated stage has a conflicting receipt")
        return manifest
    if requested_index != current_index + 1:
        raise InvalidPacketTransition("packet stages cannot be skipped or reversed")
    if not receipt:
        raise InvalidPacketTransition("each packet stage requires a receipt")
    _validate_stage_receipt(current, stage, receipt)
    receipts = dict(current.receipts)
    receipts[stage] = dict(receipt)
    updated_record = replace(current, stage=stage, receipts=receipts)
    packets = dict(manifest.packets)
    records = packets[job_id]
    packets[job_id] = (*records[:-1], updated_record)
    return replace(manifest, packets=packets)


def _validate_stage_receipt(
    record: PacketRecord,
    stage: str,
    receipt: Mapping[str, object],
) -> None:
    if stage == "posting_verified":
        if not all(
            isinstance(receipt.get(name), str) and receipt.get(name)
            for name in ("posting_url", "application_url")
        ):
            raise InvalidPacketTransition("posting verification needs exact URLs")
    elif stage == "drafted":
        if not isinstance(receipt.get("draft_hashes"), Mapping):
            raise InvalidPacketTransition("drafted stage needs draft hashes")
    elif stage == "quality_checked":
        try:
            quality = QualityReceipt.from_mapping(receipt)
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidPacketTransition("quality receipt is incomplete") from exc
        failures = validate_quality_receipt(
            quality,
            cover_letter_enabled=record.cover_letter_pdf is not None,
        )
        if failures:
            raise InvalidPacketTransition(
                "quality checks failed: " + ", ".join(failures)
            )
    elif stage == "saved":
        hashes = receipt.get("artifact_hashes")
        if not isinstance(hashes, Mapping) or "resume" not in hashes:
            raise InvalidPacketTransition("saved stage needs artifact hashes")
        if record.cover_letter_pdf is not None and "cover_letter" not in hashes:
            raise InvalidPacketTransition("cover letter hash is required")
    elif stage == "local_verified":
        if receipt.get("verified") is not True or not isinstance(
            receipt.get("artifact_hashes"), Mapping
        ):
            raise InvalidPacketTransition("local artifact readback is not verified")
    elif stage == "ready" and receipt.get("packet_ready") is not True:
        raise InvalidPacketTransition("ready stage needs canonical local delivery")


def resume_queue(manifest: ApplicationManifest) -> tuple[PacketRecord, ...]:
    return tuple(
        records[-1]
        for _, records in sorted(manifest.packets.items())
        if records and records[-1].stage != "ready"
    )


def resume_action(record: PacketRecord, current_profile_hash: str) -> str:
    if record.stage == "ready":
        return "complete"
    if record.profile_hash and record.profile_hash != current_profile_hash:
        return "restart_required"
    return "resume"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_local_artifacts(
    workspace: WorkspacePaths,
    record: PacketRecord,
) -> ArtifactVerification:
    expected = {"resume": record.resume_pdf}
    if record.cover_letter_pdf is not None:
        expected["cover_letter"] = record.cover_letter_pdf
    errors: list[str] = []
    hashes: dict[str, str] = {}
    actual_version_dir = _resolve(workspace, record.version_dir)
    for name, relative_path in expected.items():
        path = _resolve(workspace, relative_path)
        if path.parent != actual_version_dir:
            errors.append(f"{name}_not_in_version_root")
            continue
        if not path.is_file() or not path.read_bytes().startswith(b"%PDF-"):
            errors.append(f"{name}_invalid_pdf")
            continue
        hashes[name] = _hash(path)
    allowed = {path.name for path in expected.values()}
    extras = [
        path.name
        for path in actual_version_dir.glob("*.pdf")
        if path.name not in allowed
    ]
    if extras:
        errors.append("unexpected_employer_facing_pdf")
    return ArtifactVerification(not errors, tuple(errors), hashes)


def complete_local_delivery(
    workspace: WorkspacePaths,
    manifest: ApplicationManifest,
    job_id: str,
    *,
    occurred_at: str,
) -> ApplicationManifest:
    record = _latest(manifest, job_id)
    if record is None:
        raise InvalidPacketTransition("packet job is not in the manifest")
    if record.stage == "ready":
        return manifest
    if record.stage not in {"saved", "local_verified"}:
        raise InvalidPacketTransition("packet must be saved before local delivery")
    verification = verify_local_artifacts(workspace, record)
    if not verification.valid:
        raise InvalidPacketTransition(
            "local artifact checks failed: " + ", ".join(verification.errors)
        )
    saved_hashes = record.receipts.get("saved", {}).get("artifact_hashes")
    if dict(saved_hashes or {}) != dict(verification.hashes):
        raise InvalidPacketTransition("saved artifact hashes do not match local readback")
    if record.stage == "saved":
        manifest = advance_packet(
            manifest,
            job_id,
            "local_verified",
            {"verified": True, "artifact_hashes": dict(verification.hashes)},
        )
        record = _latest(manifest, job_id)
        assert record is not None
    record_application_version(
        workspace,
        job_id,
        {
            "version": record.version,
            "resume_pdf": record.resume_pdf.as_posix(),
            "cover_letter_pdf": (
                record.cover_letter_pdf.as_posix()
                if record.cover_letter_pdf is not None
                else None
            ),
            "artifact_hashes": dict(verification.hashes),
        },
        occurred_at=occurred_at,
    )
    load_indexes(workspace)
    return advance_packet(
        manifest,
        job_id,
        "ready",
        {"packet_ready": True, "canonical_job_id": job_id},
    )


def _record_to_json(record: PacketRecord) -> dict[str, object]:
    return {
        "job_id": record.job_id,
        "employer": record.employer,
        "title": record.title,
        "version": record.version,
        "version_dir": record.version_dir.as_posix(),
        "resume_pdf": record.resume_pdf.as_posix(),
        "cover_letter_pdf": (
            record.cover_letter_pdf.as_posix() if record.cover_letter_pdf else None
        ),
        "working_dir": record.working_dir.as_posix(),
        "stage": record.stage,
        "receipts": {name: dict(receipt) for name, receipt in record.receipts.items()},
        "profile_hash": record.profile_hash,
    }


def save_manifest(path: Path, manifest: ApplicationManifest) -> None:
    atomic_write_json(
        path,
        {
            "schema_version": manifest.schema_version,
            "packets": {
                job_id: [_record_to_json(record) for record in records]
                for job_id, records in sorted(manifest.packets.items())
            },
        },
    )


def _relative_path(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise InvalidPacketTransition("manifest path must be a non-empty string")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise InvalidPacketTransition("manifest path must be workspace-relative")
    return Path(*parsed.parts)


def load_manifest(path: Path) -> ApplicationManifest:
    raw = load_json(path)
    packets: dict[str, tuple[PacketRecord, ...]] = {}
    for job_id, records in raw.get("packets", {}).items():
        packets[job_id] = tuple(
            PacketRecord(
                job_id=item["job_id"],
                employer=item["employer"],
                title=item["title"],
                version=item["version"],
                version_dir=_relative_path(item["version_dir"]),
                resume_pdf=_relative_path(item["resume_pdf"]),
                cover_letter_pdf=(
                    _relative_path(item["cover_letter_pdf"])
                    if item.get("cover_letter_pdf")
                    else None
                ),
                working_dir=_relative_path(item["working_dir"]),
                stage=item["stage"],
                receipts={
                    name: dict(receipt)
                    for name, receipt in item.get("receipts", {}).items()
                },
                profile_hash=item.get("profile_hash"),
            )
            for item in records
        )
    return ApplicationManifest(
        schema_version=int(raw.get("schema_version", 1)),
        packets=packets,
    )
