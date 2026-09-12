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
    resume_pages: int = 2
    cover_letter_pages: int = 1
    profile_hash: str | None = None
    criteria_hash: str | None = None
    writing_preferences_hash: str | None = None
    role_instructions: str = ""


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
    criteria_hash: str | None = None
    writing_preferences_hash: str | None = None
    packet_options: Mapping[str, object] = field(default_factory=dict)
    role_instructions: str = ""

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


def _record_signature(record: PacketRecord) -> tuple[object, ...]:
    return (
        record.job_id,
        record.employer,
        record.title,
        record.version,
        record.version_dir,
        record.resume_pdf,
        record.cover_letter_pdf,
        record.working_dir,
        record.profile_hash,
        record.criteria_hash,
        record.writing_preferences_hash,
        tuple(sorted(record.packet_options.items())),
        record.role_instructions,
    )


def _options_mapping(options: PacketOptions) -> dict[str, object]:
    return {
        "resume_pages": options.resume_pages,
        "cover_letter_enabled": options.cover_letter_enabled,
        "cover_letter_pages": options.cover_letter_pages,
    }


def _selected_receipt(options: PacketOptions) -> dict[str, object]:
    return {
        "approved_inputs": {
            "profile_hash": options.profile_hash,
            "criteria_hash": options.criteria_hash,
            "writing_preferences_hash": options.writing_preferences_hash,
        },
        "packet_options": _options_mapping(options),
        "role_instructions": options.role_instructions,
    }


def _validate_packet_options(options: PacketOptions) -> None:
    if any(
        not isinstance(value, str) or not value
        for value in (
            options.profile_hash,
            options.criteria_hash,
            options.writing_preferences_hash,
        )
    ):
        raise InvalidPacketTransition("packet inputs require approved hashes")
    if options.resume_pages < 1:
        raise InvalidPacketTransition("packet resume page count is invalid")
    expected_cover_pages = 1 if options.cover_letter_enabled else 0
    if options.cover_letter_pages != expected_cover_pages:
        raise InvalidPacketTransition("packet cover letter options conflict")


def load_workspace_packet_options(
    workspace: WorkspacePaths,
    *,
    role_instructions: str = "",
    cover_letter_enabled: bool | None = None,
) -> PacketOptions:
    try:
        config = load_json(workspace.state / "config.json")
        onboarding = load_json(workspace.state / "onboarding-state.json")
        defaults = config["packet_defaults"]
        preferences = workspace.profile / "Writing_Preferences.md"
        writing_preferences_hash = _hash(preferences)
        configured_cover_letter = defaults["cover_letter_enabled"]
        enabled = (
            configured_cover_letter
            if cover_letter_enabled is None
            else cover_letter_enabled
        )
        options = PacketOptions(
            cover_letter_enabled=enabled,
            resume_pages=int(defaults["resume_pages"]),
            cover_letter_pages=(
                int(defaults["cover_letter_pages"])
                if enabled == configured_cover_letter
                else (1 if enabled else 0)
            ),
            profile_hash=onboarding["profile_hash"],
            criteria_hash=onboarding["criteria_hash"],
            writing_preferences_hash=writing_preferences_hash,
            role_instructions=role_instructions,
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        raise InvalidPacketTransition(
            "workspace packet defaults or approved inputs are unavailable"
        ) from exc
    _validate_packet_options(options)
    return options


def _record_matches_options(record: PacketRecord, options: PacketOptions) -> bool:
    return (
        record.profile_hash == options.profile_hash
        and record.criteria_hash == options.criteria_hash
        and record.writing_preferences_hash == options.writing_preferences_hash
        and dict(record.packet_options) == _options_mapping(options)
        and record.role_instructions == options.role_instructions
    )


def _merge_manifests(
    stored: ApplicationManifest,
    incoming: ApplicationManifest,
) -> ApplicationManifest:
    if stored.schema_version != incoming.schema_version:
        raise InvalidPacketTransition("manifest schema versions conflict")
    packets: dict[str, tuple[PacketRecord, ...]] = {}
    for job_id in sorted(set(stored.packets) | set(incoming.packets)):
        by_version: dict[str, PacketRecord] = {}
        for record in (*stored.packets.get(job_id, ()), *incoming.packets.get(job_id, ())):
            existing = by_version.get(record.version)
            if existing is None or existing == record:
                by_version[record.version] = record
                continue
            if _record_signature(existing) != _record_signature(record):
                raise InvalidPacketTransition("packet version reservation conflicts")
            existing_index = STAGES.index(existing.stage)
            record_index = STAGES.index(record.stage)
            lower, higher = (
                (existing, record)
                if existing_index <= record_index
                else (record, existing)
            )
            if any(
                dict(higher.receipts.get(stage, {})) != dict(receipt)
                for stage, receipt in lower.receipts.items()
            ):
                raise InvalidPacketTransition("packet receipt history conflicts")
            if existing_index == record_index and existing != record:
                raise InvalidPacketTransition("packet stage state conflicts")
            by_version[record.version] = higher
        packets[job_id] = tuple(by_version[name] for name in sorted(by_version))
    return ApplicationManifest(schema_version=stored.schema_version, packets=packets)


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


def _ensure_packet_directories(
    workspace: WorkspacePaths,
    record: PacketRecord,
) -> None:
    _resolve(workspace, record.version_dir).mkdir(parents=True, exist_ok=True)
    _resolve(workspace, record.working_dir).mkdir(parents=True, exist_ok=True)


def persist_manifest(
    workspace: WorkspacePaths,
    manifest: ApplicationManifest,
) -> ApplicationManifest:
    manifest_path = workspace.state / "application-manifest.json"
    with workspace_lock(workspace):
        stored = (
            load_manifest(manifest_path)
            if manifest_path.exists()
            else ApplicationManifest()
        )
        merged = _merge_manifests(stored, manifest)
        save_manifest(manifest_path, merged)
        return merged


def start_packet(
    workspace: WorkspacePaths,
    job_id: str,
    options: PacketOptions,
    manifest: ApplicationManifest,
    *,
    occurred_at: str,
    explicit_request: bool,
    restart: bool = False,
) -> tuple[ApplicationManifest, PacketRecord]:
    if not explicit_request:
        raise InvalidPacketTransition("packet preparation requires an explicit request")
    if not occurred_at:
        raise InvalidPacketTransition("occurred_at is required")
    _validate_packet_options(options)
    manifest_path = workspace.state / "application-manifest.json"
    with workspace_lock(workspace):
        stored = (
            load_manifest(manifest_path)
            if manifest_path.exists()
            else ApplicationManifest()
        )
        manifest = _merge_manifests(stored, manifest)
        current = _latest(manifest, job_id)
        try:
            read_job(workspace, job_id)
        except JobStoreError as exc:
            raise InvalidPacketTransition(
                "packet job must exist in the canonical store"
            ) from exc
        if current is not None and not restart:
            if not _record_matches_options(current, options):
                raise InvalidPacketTransition(
                    "packet inputs changed; explicit restart required"
                )
            save_manifest(manifest_path, manifest)
            _ensure_packet_directories(workspace, current)
            return manifest, current

    try:
        update_job_status(
            workspace,
            job_id,
            "prepare_application",
            occurred_at=occurred_at,
            allowed_prior_statuses=frozenset(
                {"new", "needs_confirmation", "prepare_application", "packet_ready"}
            ),
        )
    except JobStoreError as exc:
        raise InvalidPacketTransition("packet job must exist in the canonical store") from exc

    with workspace_lock(workspace):
        stored = (
            load_manifest(manifest_path)
            if manifest_path.exists()
            else ApplicationManifest()
        )
        manifest = _merge_manifests(stored, manifest)
        job = read_job(workspace, job_id)
        employer = _safe_component(str(job["employer"]))
        title = _safe_component(str(job["title"]))
        application_dir = Path("Applications") / f"{job_id}_{employer}_{title}"
        actual_application_dir = _resolve(workspace, application_dir)
        actual_application_dir.mkdir(parents=True, exist_ok=True)
        versions = [
            int(name[1:])
            for name in (path.name for path in actual_application_dir.iterdir())
            if re.fullmatch(r"v[0-9]{3}", name)
        ]
        versions.extend(
            int(record.version[1:])
            for record in manifest.packets.get(job_id, ())
            if re.fullmatch(r"v[0-9]{3}", record.version)
        )
        number = max(versions, default=0) + 1
        version = f"v{number:03d}"
        version_dir = application_dir / version
        working_dir = version_dir / "working"
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
            receipts={"selected": _selected_receipt(options)},
            profile_hash=options.profile_hash,
            criteria_hash=options.criteria_hash,
            writing_preferences_hash=options.writing_preferences_hash,
            packet_options=_options_mapping(options),
            role_instructions=options.role_instructions,
        )
        packets = dict(manifest.packets)
        packets[job_id] = (*packets.get(job_id, ()), record)
        manifest = replace(manifest, packets=packets)
        save_manifest(manifest_path, manifest)
        _ensure_packet_directories(workspace, record)
        return manifest, record


def restart_packet(
    workspace: WorkspacePaths,
    job_id: str,
    options: PacketOptions,
    manifest: ApplicationManifest,
    *,
    occurred_at: str,
    explicit_request: bool,
) -> tuple[ApplicationManifest, PacketRecord]:
    return start_packet(
        workspace,
        job_id,
        options,
        manifest,
        occurred_at=occurred_at,
        explicit_request=explicit_request,
        restart=True,
    )


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
        if record.profile_hash is not None and not isinstance(
            receipt.get("posting_snapshot_hash"), str
        ):
            raise InvalidPacketTransition(
                "posting verification needs an exact snapshot hash"
            )
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
        if record.profile_hash is not None:
            expected_bindings = {
                "profile_hash": record.profile_hash,
                "criteria_hash": record.criteria_hash,
                "writing_preferences_hash": record.writing_preferences_hash,
                "packet_options": dict(record.packet_options),
                "role_instructions": record.role_instructions,
                "posting_snapshot_hash": record.receipts.get(
                    "posting_verified", {}
                ).get("posting_snapshot_hash"),
                "draft_hashes": dict(
                    record.receipts.get("drafted", {}).get("draft_hashes", {})
                ),
                "final_pdf_hashes": dict(
                    receipt.get("bindings", {}).get("final_pdf_hashes", {})
                )
                if isinstance(receipt.get("bindings"), Mapping)
                else {},
            }
            if not isinstance(receipt.get("bindings"), Mapping) or dict(
                receipt["bindings"]
            ) != expected_bindings or not expected_bindings["final_pdf_hashes"]:
                raise InvalidPacketTransition(
                    "quality receipt binding does not match packet inputs"
                )
    elif stage == "saved":
        hashes = receipt.get("artifact_hashes")
        if not isinstance(hashes, Mapping) or "resume" not in hashes:
            raise InvalidPacketTransition("saved stage needs artifact hashes")
        if record.cover_letter_pdf is not None and "cover_letter" not in hashes:
            raise InvalidPacketTransition("cover letter hash is required")
        quality_bindings = record.receipts.get("quality_checked", {}).get("bindings")
        if isinstance(quality_bindings, Mapping) and dict(
            quality_bindings.get("final_pdf_hashes", {})
        ) != dict(hashes):
            raise InvalidPacketTransition(
                "saved artifact hashes differ from quality-reviewed PDFs"
            )
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


def resume_action(record: PacketRecord, current_inputs: PacketOptions | str) -> str:
    if record.stage == "ready":
        return "complete"
    if isinstance(current_inputs, PacketOptions):
        if not _record_matches_options(record, current_inputs):
            return "restart_required"
    elif record.profile_hash and record.profile_hash != current_inputs:
        return "restart_required"
    return "resume"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_paths(record: PacketRecord) -> dict[str, Path]:
    expected = {"resume": record.resume_pdf}
    if record.cover_letter_pdf is not None:
        expected["cover_letter"] = record.cover_letter_pdf
    return expected


def _pdf_pages(path: Path) -> int:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path), strict=True)
        pages = len(reader.pages)
    except Exception as exc:
        raise ValueError("PDF parser rejected the file") from exc
    if pages < 1:
        raise ValueError("PDF has no pages")
    return pages


def collect_local_artifacts(
    workspace: WorkspacePaths,
    record: PacketRecord,
) -> ArtifactVerification:
    expected = _artifact_paths(record)
    errors: list[str] = []
    hashes: dict[str, str] = {}
    actual_version_dir = _resolve(workspace, record.version_dir)
    for name, relative_path in expected.items():
        path = _resolve(workspace, relative_path)
        if path.parent != actual_version_dir:
            errors.append(f"{name}_not_in_version_root")
            continue
        if not path.is_file():
            errors.append(f"{name}_missing")
            continue
        try:
            _pdf_pages(path)
        except ValueError:
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


def verify_local_artifacts(
    workspace: WorkspacePaths,
    record: PacketRecord,
) -> ArtifactVerification:
    collected = collect_local_artifacts(workspace, record)
    errors = list(collected.errors)
    expected_names = set(_artifact_paths(record))
    receipts: list[tuple[str, Mapping[str, object]]] = []
    for stage in ("saved", "local_verified", "ready"):
        hashes = record.receipts.get(stage, {}).get("artifact_hashes")
        if isinstance(hashes, Mapping):
            receipts.append((stage, hashes))

    try:
        canonical = read_job(workspace, record.job_id)
    except JobStoreError:
        canonical = {}
    delivered = [
        version
        for version in canonical.get("application_versions", ())
        if isinstance(version, Mapping) and version.get("version") == record.version
    ]
    if delivered:
        delivery = delivered[0]
        hashes = delivery.get("artifact_hashes")
        if isinstance(hashes, Mapping):
            receipts.append(("delivered", hashes))
        expected_paths = {
            "resume_pdf": record.resume_pdf.as_posix(),
            "cover_letter_pdf": (
                record.cover_letter_pdf.as_posix()
                if record.cover_letter_pdf is not None
                else None
            ),
        }
        if any(delivery.get(name) != value for name, value in expected_paths.items()):
            errors.append("delivered_artifact_path_mismatch")
    elif record.stage == "ready":
        errors.append("delivered_receipt_missing")

    if not receipts:
        errors.append("recorded_artifact_hashes_missing")
    for source, expected_hashes in receipts:
        if set(expected_hashes) != expected_names:
            errors.append(f"{source}_artifact_identity_mismatch")
            continue
        for name in sorted(expected_names):
            if collected.hashes.get(name) != expected_hashes.get(name):
                errors.append(f"{name}_hash_mismatch")
    return ArtifactVerification(
        not errors,
        tuple(dict.fromkeys(errors)),
        collected.hashes,
    )


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
    if record.stage not in {"saved", "local_verified", "ready"}:
        raise InvalidPacketTransition("packet must be saved before local delivery")
    verification = verify_local_artifacts(workspace, record)
    if not verification.valid:
        raise InvalidPacketTransition(
            "local artifact checks failed: " + ", ".join(verification.errors)
        )
    if record.stage == "saved":
        manifest = advance_packet(
            manifest,
            job_id,
            "local_verified",
            {"verified": True, "artifact_hashes": dict(verification.hashes)},
        )
        manifest = persist_manifest(workspace, manifest)
        record = _latest(manifest, job_id)
        assert record is not None
    delivery_receipt = {
        "version": record.version,
        "resume_pdf": record.resume_pdf.as_posix(),
        "cover_letter_pdf": (
            record.cover_letter_pdf.as_posix()
            if record.cover_letter_pdf is not None
            else None
        ),
        "artifact_hashes": dict(verification.hashes),
    }
    record_application_version(
        workspace,
        job_id,
        delivery_receipt,
        occurred_at=occurred_at,
    )
    load_indexes(workspace)
    if record.stage == "ready":
        return persist_manifest(workspace, manifest)
    completed = advance_packet(
        manifest,
        job_id,
        "ready",
        {
            "packet_ready": True,
            "canonical_job_id": job_id,
            "artifact_hashes": dict(verification.hashes),
        },
    )
    return persist_manifest(workspace, completed)


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
        loaded_records: list[PacketRecord] = []
        for item in records:
            receipts = {
                name: dict(receipt)
                for name, receipt in item.get("receipts", {}).items()
            }
            selected = receipts.get("selected", {})
            approved_inputs = selected.get("approved_inputs", {})
            if not isinstance(approved_inputs, Mapping):
                approved_inputs = {}
            packet_options = item.get("packet_options") or selected.get(
                "packet_options"
            )
            if not isinstance(packet_options, Mapping):
                packet_options = {
                    "resume_pages": 2,
                    "cover_letter_enabled": bool(item.get("cover_letter_pdf")),
                    "cover_letter_pages": 1 if item.get("cover_letter_pdf") else 0,
                }
            loaded_records.append(PacketRecord(
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
                receipts=receipts,
                profile_hash=(
                    item.get("profile_hash") or approved_inputs.get("profile_hash")
                ),
                criteria_hash=(
                    item.get("criteria_hash") or approved_inputs.get("criteria_hash")
                ),
                writing_preferences_hash=(
                    item.get("writing_preferences_hash")
                    or approved_inputs.get("writing_preferences_hash")
                ),
                packet_options=dict(packet_options),
                role_instructions=str(
                    item.get("role_instructions", selected.get("role_instructions", ""))
                ),
            ))
        packets[job_id] = tuple(loaded_records)
    return ApplicationManifest(
        schema_version=int(raw.get("schema_version", 1)),
        packets=packets,
    )
