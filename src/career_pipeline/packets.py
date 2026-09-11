"""Versioned local packet paths, manifests, transitions, and hash checks."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping

from .atomic import atomic_write_json, load_json
from .contracts import WorkspacePaths
from .quality import QualityReceipt, validate_quality_receipt


STAGES = (
    "selected",
    "posting_verified",
    "drafted",
    "quality_checked",
    "saved",
    "uploaded",
    "delivery_verified",
    "ready",
)


class InvalidPacketTransition(ValueError):
    pass


@dataclass(frozen=True)
class PacketOptions:
    cover_letter_enabled: bool = True
    profile_hash: str | None = None


@dataclass(frozen=True)
class PacketTicket:
    ticket_id: str
    employer: str
    title: str
    posting_url: str
    application_url: str


@dataclass(frozen=True)
class PacketRecord:
    ticket_id: str
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


def _safe_component(value: str, *, allow_hyphen: bool = True) -> str:
    separator = "_" if allow_hyphen else "-"
    cleaned = _UNSAFE.sub(separator, value.strip())
    cleaned = _UNDERSCORES.sub("_", cleaned).strip("_-")
    if not cleaned:
        raise ValueError("packet path component is empty after sanitization")
    if len(cleaned) <= 72:
        return cleaned
    suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned[:63].rstrip('_-')}_{suffix}"


def _latest(manifest: ApplicationManifest, ticket_id: str) -> PacketRecord | None:
    records = manifest.packets.get(ticket_id, ())
    return records[-1] if records else None


def start_packet(
    ticket: PacketTicket,
    workspace: WorkspacePaths,
    options: PacketOptions,
    manifest: ApplicationManifest,
) -> tuple[ApplicationManifest, PacketRecord]:
    current = _latest(manifest, ticket.ticket_id)
    if current is not None and current.stage != "ready":
        return manifest, current

    ticket_name = _safe_component(ticket.ticket_id)
    employer = _safe_component(ticket.employer)
    title = _safe_component(ticket.title)
    job_dir = workspace.applications / f"{ticket_name}_{employer}_{title}"
    job_dir.mkdir(parents=True, exist_ok=True)
    lock_path = job_dir / ".packet.lock"
    try:
        descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise InvalidPacketTransition("packet version allocation is already running") from exc
    try:
        os.close(descriptor)
        versions = [
            int(path.name[1:])
            for path in job_dir.iterdir()
            if path.is_dir() and re.fullmatch(r"v\d{3}", path.name)
        ]
        number = max(versions, default=0) + 1
        version = f"v{number:03d}"
        version_dir = job_dir / version
        version_dir.mkdir()
        working_dir = version_dir / "working"
        working_dir.mkdir()
    finally:
        lock_path.unlink(missing_ok=True)

    record = PacketRecord(
        ticket_id=ticket.ticket_id,
        employer=ticket.employer,
        title=ticket.title,
        version=version,
        version_dir=version_dir,
        resume_pdf=version_dir / f"Resume_{employer}_{title}.pdf",
        cover_letter_pdf=(
            version_dir / f"Cover_Letter_{employer}_{title}.pdf"
            if options.cover_letter_enabled
            else None
        ),
        working_dir=working_dir,
        profile_hash=options.profile_hash,
    )
    packets = dict(manifest.packets)
    packets[ticket.ticket_id] = (*packets.get(ticket.ticket_id, ()), record)
    return replace(manifest, packets=packets), record


def advance_packet(
    manifest: ApplicationManifest,
    ticket_id: str,
    stage: str,
    receipt: Mapping[str, object],
) -> ApplicationManifest:
    current = _latest(manifest, ticket_id)
    if current is None:
        raise InvalidPacketTransition("packet ticket is not in the manifest")
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
    records = packets[ticket_id]
    packets[ticket_id] = (*records[:-1], updated_record)
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
    elif stage == "uploaded":
        attachments = receipt.get("attachment_ids")
        if not isinstance(attachments, list) or not attachments:
            raise InvalidPacketTransition("uploaded stage needs attachment IDs")
    elif stage == "delivery_verified":
        if receipt.get("verified") is not True or not isinstance(
            receipt.get("attachment_hashes"), Mapping
        ):
            raise InvalidPacketTransition("delivery readback is not verified")
    elif stage == "ready" and receipt.get("packet_ready") is not True:
        raise InvalidPacketTransition("ready stage needs a verified label receipt")


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


def verify_local_artifacts(record: PacketRecord) -> ArtifactVerification:
    expected = {"resume": record.resume_pdf}
    if record.cover_letter_pdf is not None:
        expected["cover_letter"] = record.cover_letter_pdf
    errors: list[str] = []
    hashes: dict[str, str] = {}
    for name, path in expected.items():
        if path.parent != record.version_dir:
            errors.append(f"{name}_not_in_version_root")
            continue
        if not path.is_file() or not path.read_bytes().startswith(b"%PDF-"):
            errors.append(f"{name}_invalid_pdf")
            continue
        hashes[name] = _hash(path)
    allowed = {path.name for path in expected.values()}
    extras = [
        path.name
        for path in record.version_dir.glob("*.pdf")
        if path.name not in allowed
    ]
    if extras:
        errors.append("unexpected_employer_facing_pdf")
    return ArtifactVerification(not errors, tuple(errors), hashes)


def _record_to_json(record: PacketRecord) -> dict[str, object]:
    return {
        "ticket_id": record.ticket_id,
        "employer": record.employer,
        "title": record.title,
        "version": record.version,
        "version_dir": str(record.version_dir),
        "resume_pdf": str(record.resume_pdf),
        "cover_letter_pdf": (
            str(record.cover_letter_pdf) if record.cover_letter_pdf else None
        ),
        "working_dir": str(record.working_dir),
        "stage": record.stage,
        "receipts": {
            name: dict(receipt) for name, receipt in record.receipts.items()
        },
        "profile_hash": record.profile_hash,
    }


def save_manifest(path: Path, manifest: ApplicationManifest) -> None:
    atomic_write_json(
        path,
        {
            "schema_version": manifest.schema_version,
            "packets": {
                ticket_id: [_record_to_json(record) for record in records]
                for ticket_id, records in sorted(manifest.packets.items())
            },
        },
    )


def load_manifest(path: Path) -> ApplicationManifest:
    raw = load_json(path)
    packets: dict[str, tuple[PacketRecord, ...]] = {}
    for ticket_id, records in raw.get("packets", {}).items():
        packets[ticket_id] = tuple(
            PacketRecord(
                ticket_id=item["ticket_id"],
                employer=item["employer"],
                title=item["title"],
                version=item["version"],
                version_dir=Path(item["version_dir"]),
                resume_pdf=Path(item["resume_pdf"]),
                cover_letter_pdf=(
                    Path(item["cover_letter_pdf"])
                    if item.get("cover_letter_pdf")
                    else None
                ),
                working_dir=Path(item["working_dir"]),
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
