"""Immediate, versioned application packets delivered to the local workspace."""

from __future__ import annotations

import hashlib
import json
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
    workspace_lock_if_needed,
)
from .quality import QualityReceipt, validate_quality_receipt
from .resume_layout import LayoutMeasurementError, measure_resume_layout, validate_layout_receipt
from .timestamps import TimestampError, parse_instant


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
    resume_layout: Mapping[str, object] | None = None


_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")
_UNDERSCORES = re.compile(r"_+")
_SHA256 = re.compile(r"[a-f0-9]{64}")
_LAYOUT_REVALIDATED = "layout_revalidated"
_MANIFEST_KEYS = frozenset({"schema_version", "packets"})
_MANIFEST_RECORD_REQUIRED_KEYS = frozenset(
    {
        "job_id",
        "employer",
        "title",
        "version",
        "version_dir",
        "resume_pdf",
        "working_dir",
        "stage",
        "receipts",
    }
)
_MANIFEST_RECORD_KEYS = _MANIFEST_RECORD_REQUIRED_KEYS | {
    "cover_letter_pdf",
    "profile_hash",
}


def _safe_component(value: str) -> str:
    cleaned = _UNSAFE.sub("_", value.strip())
    cleaned = _UNDERSCORES.sub("_", cleaned).strip("_-")
    if not cleaned:
        raise ValueError("packet path component is empty after sanitization")
    if len(cleaned) <= 72:
        return cleaned
    suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned[:63].rstrip('_-')}_{suffix}"


def validate_manifest_contract(raw: Mapping[str, object]) -> None:
    """Validate the persisted v1 JSON contract without loader coercion."""

    if set(raw) != _MANIFEST_KEYS or type(raw.get("schema_version")) is not int:
        raise InvalidPacketTransition("application manifest contract is invalid")
    packets = raw.get("packets")
    if raw["schema_version"] != 1 or not isinstance(packets, Mapping):
        raise InvalidPacketTransition("application manifest contract is invalid")
    for job_id, records in packets.items():
        if (
            not isinstance(job_id, str)
            or re.fullmatch(r"JOB-[0-9]{6}", job_id) is None
            or not isinstance(records, list)
        ):
            raise InvalidPacketTransition("application manifest contract is invalid")
        for item in records:
            if (
                not isinstance(item, Mapping)
                or not _MANIFEST_RECORD_REQUIRED_KEYS.issubset(item)
                or not set(item).issubset(_MANIFEST_RECORD_KEYS)
            ):
                raise InvalidPacketTransition("application manifest contract is invalid")
            if (
                not isinstance(item["job_id"], str)
                or re.fullmatch(r"JOB-[0-9]{6}", item["job_id"]) is None
                or not isinstance(item["employer"], str)
                or not item["employer"]
                or not isinstance(item["title"], str)
                or not item["title"]
                or not isinstance(item["version"], str)
                or re.fullmatch(r"v[0-9]{3}", item["version"]) is None
                or any(
                    not isinstance(item[name], str) or not item[name]
                    for name in ("version_dir", "resume_pdf", "working_dir")
                )
                or not isinstance(item["stage"], str)
                or item["stage"] not in STAGES
                or not isinstance(item["receipts"], Mapping)
            ):
                raise InvalidPacketTransition("application manifest contract is invalid")
            cover_letter_pdf = item.get("cover_letter_pdf")
            profile_hash = item.get("profile_hash")
            if (
                cover_letter_pdf is not None
                and (not isinstance(cover_letter_pdf, str) or not cover_letter_pdf)
            ) or (profile_hash is not None and not isinstance(profile_hash, str)):
                raise InvalidPacketTransition("application manifest contract is invalid")
            receipts = item["receipts"]
            if any(
                not isinstance(name, str) or not isinstance(receipt, Mapping)
                for name, receipt in receipts.items()
            ):
                raise InvalidPacketTransition("application manifest contract is invalid")


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


def _expected_artifact_names(record: PacketRecord) -> frozenset[str]:
    names = {"resume"}
    if record.cover_letter_pdf is not None:
        names.add("cover_letter")
    return frozenset(names)


def _valid_hashes(value: object, expected: frozenset[str]) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == expected
        and all(
            isinstance(item, str) and _SHA256.fullmatch(item) is not None
            for item in value.values()
        )
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
            if _LAYOUT_REVALIDATED in record.receipts:
                validate_packet_history(record)
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
                if stage != _LAYOUT_REVALIDATED
            ):
                raise InvalidPacketTransition("packet receipt history conflicts")
            if existing_index == record_index and (
                {key: value for key, value in existing.receipts.items() if key != _LAYOUT_REVALIDATED}
                != {key: value for key, value in record.receipts.items() if key != _LAYOUT_REVALIDATED}
            ):
                raise InvalidPacketTransition("packet stage state conflicts")
            existing_audit = existing.receipts.get(_LAYOUT_REVALIDATED)
            incoming_audit = record.receipts.get(_LAYOUT_REVALIDATED)
            if existing_audit is not None and incoming_audit is not None and existing_audit != incoming_audit:
                raise InvalidPacketTransition("packet layout revalidation receipt conflicts")
            receipts = dict(higher.receipts)
            if existing_audit is not None or incoming_audit is not None:
                receipts[_LAYOUT_REVALIDATED] = existing_audit if existing_audit is not None else incoming_audit
            by_version[record.version] = replace(higher, receipts=receipts)
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
    with workspace_lock_if_needed(workspace):
        stored = (
            load_manifest(manifest_path)
            if manifest_path.exists()
            else ApplicationManifest()
        )
        merged = _merge_manifests(stored, manifest)
        save_manifest(manifest_path, merged)
        return merged


def _delivery_record(
    workspace: WorkspacePaths,
    manifest: ApplicationManifest,
    job_id: str,
) -> tuple[ApplicationManifest, PacketRecord]:
    requested = _latest(manifest, job_id)
    if requested is None:
        raise InvalidPacketTransition("packet job is not in the manifest")
    manifest_path = workspace.state / "application-manifest.json"
    with workspace_lock_if_needed(workspace):
        stored = (
            load_manifest(manifest_path)
            if manifest_path.exists()
            else ApplicationManifest()
        )
        reconciled = _merge_manifests(stored, manifest)
        latest = _latest(reconciled, job_id)
        if latest is None or latest.version != requested.version:
            raise InvalidPacketTransition(
                f"packet version {requested.version} is superseded"
            )
        return reconciled, latest


def _require_delivery_version(
    manifest: ApplicationManifest,
    job_id: str,
    version: str,
) -> PacketRecord:
    latest = _latest(manifest, job_id)
    if latest is None or latest.version != version:
        raise InvalidPacketTransition(f"packet version {version} is superseded")
    return latest


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
            require_no_packet_reservation=not restart,
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
        current = _latest(manifest, job_id)
        if current is not None and not restart:
            if not _record_matches_options(current, options):
                raise InvalidPacketTransition(
                    "packet inputs changed; explicit restart required"
                )
            save_manifest(manifest_path, manifest)
            _ensure_packet_directories(workspace, current)
            return manifest, current
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
    *,
    workspace: WorkspacePaths | None = None,
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
        if stage in {"quality_checked", "ready"}:
            _validate_stage_receipt(current, stage, receipt)
            _require_measured_artifacts(workspace, current, stage, receipt)
        return manifest
    if requested_index != current_index + 1:
        raise InvalidPacketTransition("packet stages cannot be skipped or reversed")
    if not receipt:
        raise InvalidPacketTransition("each packet stage requires a receipt")
    _validate_stage_receipt(current, stage, receipt)
    if stage in {"quality_checked", "ready"}:
        _require_measured_artifacts(workspace, current, stage, receipt)
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
    *,
    require_layout: bool = True,
) -> None:
    if stage == "posting_verified":
        if not all(
            isinstance(receipt.get(name), str) and receipt.get(name)
            for name in ("posting_url", "application_url")
        ):
            raise InvalidPacketTransition("posting verification needs exact URLs")
        snapshot_hash = receipt.get("posting_snapshot_hash")
        if (
            not isinstance(snapshot_hash, str)
            or _SHA256.fullmatch(snapshot_hash) is None
        ):
            raise InvalidPacketTransition(
                "posting verification needs an exact snapshot hash"
            )
    elif stage == "drafted":
        if not _valid_hashes(
            receipt.get("draft_hashes"), _expected_artifact_names(record)
        ):
            raise InvalidPacketTransition(
                "draft hashes must identify every expected document"
            )
    elif stage == "quality_checked":
        try:
            quality = QualityReceipt.from_mapping(receipt)
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidPacketTransition("quality receipt is incomplete") from exc
        failures = validate_quality_receipt(
            quality,
            cover_letter_enabled=record.cover_letter_pdf is not None,
            require_layout=require_layout,
        )
        if failures:
            raise InvalidPacketTransition(
                "quality checks failed: " + ", ".join(failures)
            )
        if record.profile_hash is not None:
            bindings = receipt.get("bindings")
            final_pdf_hashes = (
                bindings.get("final_pdf_hashes")
                if isinstance(bindings, Mapping)
                else None
            )
            if not _valid_hashes(
                final_pdf_hashes, _expected_artifact_names(record)
            ):
                raise InvalidPacketTransition(
                    "quality receipt binding does not match packet inputs"
                )
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
                "final_pdf_hashes": dict(final_pdf_hashes),
            }
            if dict(bindings) != expected_bindings:
                raise InvalidPacketTransition(
                    "quality receipt binding does not match packet inputs"
                )
    elif stage == "saved":
        hashes = receipt.get("artifact_hashes")
        if not _valid_hashes(hashes, _expected_artifact_names(record)):
            raise InvalidPacketTransition(
                "saved stage needs exact artifact hashes"
            )
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


def _validate_selected_receipt(
    record: PacketRecord,
    receipt: Mapping[str, object],
) -> None:
    if set(receipt) != {"approved_inputs", "packet_options", "role_instructions"}:
        raise InvalidPacketTransition("selected packet receipt is invalid")
    approved_inputs = receipt.get("approved_inputs")
    packet_options = receipt.get("packet_options")
    role_instructions = receipt.get("role_instructions")
    if (
        not isinstance(approved_inputs, Mapping)
        or set(approved_inputs)
        != {"profile_hash", "criteria_hash", "writing_preferences_hash"}
        or any(
            not isinstance(value, str) or not value
            for value in approved_inputs.values()
        )
        or not isinstance(packet_options, Mapping)
        or set(packet_options)
        != {"resume_pages", "cover_letter_enabled", "cover_letter_pages"}
        or type(packet_options.get("resume_pages")) is not int
        or packet_options["resume_pages"] < 1
        or not isinstance(packet_options.get("cover_letter_enabled"), bool)
        or type(packet_options.get("cover_letter_pages")) is not int
        or packet_options["cover_letter_pages"]
        != (1 if packet_options["cover_letter_enabled"] else 0)
        or not isinstance(role_instructions, str)
    ):
        raise InvalidPacketTransition("selected packet receipt is invalid")
    options = PacketOptions(
        cover_letter_enabled=packet_options["cover_letter_enabled"],
        resume_pages=packet_options["resume_pages"],
        cover_letter_pages=packet_options["cover_letter_pages"],
        profile_hash=record.profile_hash,
        criteria_hash=record.criteria_hash,
        writing_preferences_hash=record.writing_preferences_hash,
        role_instructions=record.role_instructions,
    )
    _validate_packet_options(options)
    if (
        dict(receipt) != _selected_receipt(options)
        or bool(record.cover_letter_pdf) != options.cover_letter_enabled
    ):
        raise InvalidPacketTransition("selected packet receipt is invalid")


def validate_packet_history(record: PacketRecord) -> None:
    """Validate persisted progress by replaying packet-stage receipt rules."""

    if record.stage not in STAGES:
        raise InvalidPacketTransition("packet stage is invalid")
    stage_index = STAGES.index(record.stage)
    receipt_names = set(record.receipts)
    allowed_receipts = set(STAGES[: stage_index + 1])
    if stage_index >= STAGES.index("quality_checked"):
        allowed_receipts.add(_LAYOUT_REVALIDATED)
    required_progress_receipts = set(STAGES[1 : stage_index + 1])
    if (
        not receipt_names.issubset(allowed_receipts)
        or not required_progress_receipts.issubset(receipt_names)
        or any(
            not isinstance(name, str) or not isinstance(receipt, Mapping)
            for name, receipt in record.receipts.items()
        )
    ):
        raise InvalidPacketTransition("packet receipt history is invalid")
    selected_receipt = record.receipts.get("selected")
    if selected_receipt is not None:
        if not selected_receipt:
            raise InvalidPacketTransition("selected packet receipt is invalid")
        _validate_selected_receipt(record, selected_receipt)
    # Legacy v1 selected records explicitly omit input bindings. The compatibility
    # loader and stage API support that omission; every later receipt remains required.
    for stage in STAGES[1 : stage_index + 1]:
        receipt = record.receipts[stage]
        if not receipt:
            raise InvalidPacketTransition("packet stage receipt is empty")
        # Historical packets remain readable. Explicit advancement and delivery
        # remeasure final PDFs under the current policy before reporting readiness.
        _validate_stage_receipt(record, stage, receipt, require_layout=False)
    if _LAYOUT_REVALIDATED in record.receipts:
        _validate_layout_revalidation(record, record.receipts[_LAYOUT_REVALIDATED])


def _legacy_quality_receipt(record: PacketRecord) -> Mapping[str, object]:
    quality = record.receipts.get("quality_checked", {})
    if "resume_layout" in quality:
        raise InvalidPacketTransition("layout revalidation is only for legacy receipts without resume_layout")
    if record.profile_hash is None or not isinstance(quality.get("bindings"), Mapping):
        raise InvalidPacketTransition("legacy layout revalidation requires the original bound editorial approval")
    _validate_stage_receipt(record, "quality_checked", quality, require_layout=False)
    return quality


def _receipt_hash(receipt: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(receipt), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_layout_revalidation(record: PacketRecord, receipt: Mapping[str, object]) -> None:
    quality = _legacy_quality_receipt(record)
    if (
        set(receipt) != {"schema_version", "scope", "reviewer", "occurred_at", "quality_receipt_sha256",
                         "artifact_hashes", "resume_layout"}
        or type(receipt.get("schema_version")) is not int
        or receipt["schema_version"] != 1
        or receipt.get("scope") != "legacy_layout_only"
        or not isinstance(receipt.get("reviewer"), str)
        or not receipt["reviewer"].strip()
    ):
        raise InvalidPacketTransition("legacy layout revalidation receipt is invalid")
    try:
        parse_instant(receipt.get("occurred_at"))
    except TimestampError as exc:
        raise InvalidPacketTransition("layout revalidation requires a timezone-aware occurred_at") from exc
    if (
        receipt.get("quality_receipt_sha256") != _receipt_hash(quality)
        or receipt.get("artifact_hashes") != quality["bindings"]["final_pdf_hashes"]
    ):
        raise InvalidPacketTransition("layout revalidation does not match the original quality receipt")
    failures = validate_layout_receipt(receipt.get("resume_layout"))
    if failures:
        raise InvalidPacketTransition("layout revalidation failed: " + ", ".join(failures))
    if receipt["resume_layout"]["pdf_sha256"] != receipt["artifact_hashes"]["resume"]:
        raise InvalidPacketTransition("layout revalidation PDF hash does not match the original artifacts")


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
    return _parse_classic_pdf(path.read_bytes())


def _pdf_line(data: bytes, position: int) -> tuple[bytes, int]:
    end = data.find(b"\n", position)
    if end < 0:
        return data[position:].rstrip(b"\r"), len(data)
    return data[position:end].rstrip(b"\r"), end + 1


def _parse_classic_pdf(data: bytes) -> int:
    """Validate a classic-xref PDF and return its traversed page count."""
    if re.match(rb"%PDF-[12]\.[0-9](?:\r?\n|\r)", data) is None:
        raise ValueError("PDF header is invalid")
    tail = re.search(rb"startxref\s+([0-9]+)\s+%%EOF\s*$", data[-4096:])
    if tail is None:
        raise ValueError("PDF trailer is invalid")
    xref_offset = int(tail.group(1))
    if xref_offset < 0 or data[xref_offset : xref_offset + 4] != b"xref":
        raise ValueError("PDF xref offset is invalid")

    position = xref_offset
    line, position = _pdf_line(data, position)
    if line != b"xref":
        raise ValueError("PDF xref table is invalid")
    active: dict[tuple[int, int], int] = {}
    while True:
        line, position = _pdf_line(data, position)
        if line == b"trailer":
            break
        section = re.fullmatch(rb"([0-9]+)\s+([0-9]+)", line)
        if section is None:
            raise ValueError("PDF xref section is invalid")
        first, count = (int(value) for value in section.groups())
        if count < 1:
            raise ValueError("PDF xref section is empty")
        for number in range(first, first + count):
            entry, position = _pdf_line(data, position)
            parsed = re.fullmatch(
                rb"([0-9]{10})\s+([0-9]{5})\s+([fn])\s*", entry
            )
            if parsed is None:
                raise ValueError("PDF xref entry is invalid")
            if parsed.group(3) == b"n":
                active[(number, int(parsed.group(2)))] = int(parsed.group(1))

    trailer_end = data.find(b"startxref", position)
    if trailer_end < 0:
        raise ValueError("PDF trailer is incomplete")
    trailer = data[position:trailer_end]
    if re.search(rb"/Encrypt\b", trailer):
        raise ValueError("encrypted PDFs are not supported")
    root_match = re.search(rb"/Root\s+([0-9]+)\s+([0-9]+)\s+R\b", trailer)
    if root_match is None:
        raise ValueError("PDF root is missing")
    root_ref = (int(root_match.group(1)), int(root_match.group(2)))

    objects: dict[tuple[int, int], bytes] = {}
    for reference, offset in active.items():
        if not 0 <= offset < len(data):
            raise ValueError("PDF object offset is invalid")
        header = re.match(rb"([0-9]+)\s+([0-9]+)\s+obj\b", data[offset:])
        if header is None or (
            int(header.group(1)), int(header.group(2))
        ) != reference:
            raise ValueError("PDF xref does not identify its object")
        body_start = offset + header.end()
        body_end = data.find(b"endobj", body_start)
        if body_end < 0:
            raise ValueError("PDF object is incomplete")
        objects[reference] = data[body_start:body_end]

    root = objects.get(root_ref)
    if root is None or re.search(rb"/Type\s*/Catalog\b", root) is None:
        raise ValueError("PDF catalog is invalid")
    pages_match = re.search(rb"/Pages\s+([0-9]+)\s+([0-9]+)\s+R\b", root)
    if pages_match is None:
        raise ValueError("PDF page tree is missing")
    pages_ref = (int(pages_match.group(1)), int(pages_match.group(2)))

    def count_pages(reference: tuple[int, int], visiting: set[tuple[int, int]]) -> int:
        if reference in visiting:
            raise ValueError("PDF page tree contains a cycle")
        body = objects.get(reference)
        if body is None:
            raise ValueError("PDF page tree references a missing object")
        if re.search(rb"/Type\s*/Page(?!s)\b", body):
            return 1
        if re.search(rb"/Type\s*/Pages\b", body) is None:
            raise ValueError("PDF page tree node is invalid")
        kids = re.search(rb"/Kids\s*\[(.*?)\]", body, re.DOTALL)
        declared = re.search(rb"/Count\s+([0-9]+)\b", body)
        if kids is None or declared is None:
            raise ValueError("PDF pages node is incomplete")
        references = [
            (int(number), int(generation))
            for number, generation in re.findall(
                rb"([0-9]+)\s+([0-9]+)\s+R\b", kids.group(1)
            )
        ]
        if not references:
            raise ValueError("PDF pages node has no children")
        visiting.add(reference)
        actual = sum(count_pages(child, visiting) for child in references)
        visiting.remove(reference)
        if actual != int(declared.group(1)):
            raise ValueError("PDF page count does not match its tree")
        return actual

    pages = count_pages(pages_ref, set())
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
    layout: Mapping[str, object] | None = None
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
            pages = _pdf_pages(path)
        except ValueError:
            errors.append(f"{name}_invalid_pdf")
            continue
        hashes[name] = _hash(path)
        if pages != (2 if name == "resume" else 1):
            errors.append(f"{name}_page_count")
        if name == "resume":
            try:
                layout = measure_resume_layout(path)
            except LayoutMeasurementError as exc:
                errors.append(f"resume_layout_measurement_error: {exc}")
            else:
                if layout["pdf_sha256"] != hashes[name]:
                    errors.append("resume_changed_during_measurement")
                if layout["passed"] is not True:
                    errors.extend(str(error) for error in layout["errors"])
    allowed = {path.name for path in expected.values()}
    extras = [
        path.name
        for path in actual_version_dir.glob("*.pdf")
        if path.name not in allowed
    ]
    if extras:
        errors.append("unexpected_employer_facing_pdf")
    return ArtifactVerification(not errors, tuple(dict.fromkeys(errors)), hashes, layout)


def _require_measured_artifacts(
    workspace: WorkspacePaths | None,
    record: PacketRecord,
    stage: str,
    receipt: Mapping[str, object],
) -> None:
    if workspace is None:
        raise InvalidPacketTransition("workspace is required to independently measure final PDFs")
    if stage == "ready":
        verified = verify_local_artifacts(workspace, record)
    else:
        verified = collect_local_artifacts(workspace, record)
    errors = list(verified.errors)
    if stage == "quality_checked":
        if verified.resume_layout != receipt.get("resume_layout"):
            errors.append("resume_layout_does_not_match_final_pdf")
        bindings = receipt.get("bindings")
        if isinstance(bindings, Mapping) and bindings.get("final_pdf_hashes") != dict(verified.hashes):
            errors.append("quality_pdf_hashes_do_not_match_final_files")
    if errors:
        raise InvalidPacketTransition("final PDF checks failed: " + ", ".join(dict.fromkeys(errors)))


def verify_local_artifacts(
    workspace: WorkspacePaths,
    record: PacketRecord,
) -> ArtifactVerification:
    collected = collect_local_artifacts(workspace, record)
    errors = list(collected.errors)
    recorded_layout = record.receipts.get("quality_checked", {}).get("resume_layout")
    if _LAYOUT_REVALIDATED in record.receipts:
        try:
            validate_packet_history(record)
        except InvalidPacketTransition as exc:
            errors.append(str(exc))
        else:
            recorded_layout = record.receipts[_LAYOUT_REVALIDATED]["resume_layout"]
    errors.extend(validate_layout_receipt(recorded_layout))
    if recorded_layout != collected.resume_layout:
        errors.append("resume_layout_does_not_match_final_pdf")
    expected_names = set(_artifact_paths(record))
    receipts: list[tuple[str, Mapping[str, object]]] = []
    quality_bindings = record.receipts.get("quality_checked", {}).get("bindings")
    if isinstance(quality_bindings, Mapping) and isinstance(quality_bindings.get("final_pdf_hashes"), Mapping):
        receipts.append(("quality_checked", quality_bindings["final_pdf_hashes"]))
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
        collected.resume_layout,
    )


def revalidate_legacy_packet_layout(
    workspace: WorkspacePaths,
    manifest: ApplicationManifest,
    job_id: str,
    *,
    reviewer: str,
    occurred_at: str,
) -> ApplicationManifest:
    """Append a layout-only audit without changing prior approval or packet stage.

    Only legacy packets with an intact, hash-bound editorial approval qualify.
    Existing audits are rechecked and reused; they can never be overwritten.
    """
    with workspace_lock(workspace):
        manifest, record = _delivery_record(workspace, manifest, job_id)
        if STAGES.index(record.stage) < STAGES.index("quality_checked"):
            raise InvalidPacketTransition("legacy layout revalidation requires an existing quality approval")
        validate_packet_history(record)
        quality = _legacy_quality_receipt(record)
        if _LAYOUT_REVALIDATED not in record.receipts:
            measured = collect_local_artifacts(workspace, record)
            if not measured.valid:
                raise InvalidPacketTransition("final PDF checks failed: " + ", ".join(measured.errors))
            audit = {
                "schema_version": 1,
                "scope": "legacy_layout_only",
                "reviewer": reviewer,
                "occurred_at": occurred_at,
                "quality_receipt_sha256": _receipt_hash(quality),
                "artifact_hashes": dict(measured.hashes),
                "resume_layout": measured.resume_layout,
            }
            _validate_layout_revalidation(record, audit)
            record = replace(record, receipts={**record.receipts, _LAYOUT_REVALIDATED: audit})
            packets = dict(manifest.packets)
            packets[job_id] = (*packets[job_id][:-1], record)
            manifest = replace(manifest, packets=packets)
        verification = verify_local_artifacts(workspace, record)
        if not verification.valid:
            raise InvalidPacketTransition("local artifact checks failed: " + ", ".join(verification.errors))
        return persist_manifest(workspace, manifest)


def complete_local_delivery(
    workspace: WorkspacePaths,
    manifest: ApplicationManifest,
    job_id: str,
    *,
    occurred_at: str,
) -> ApplicationManifest:
    manifest, record = _delivery_record(workspace, manifest, job_id)
    delivery_version = record.version
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
        record = _require_delivery_version(manifest, job_id, delivery_version)
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
    try:
        record_application_version(
            workspace,
            job_id,
            delivery_receipt,
            occurred_at=occurred_at,
            expected_latest_packet_version=delivery_version,
        )
    except JobStoreError as exc:
        if str(exc) == "packet version is superseded":
            raise InvalidPacketTransition(
                f"packet version {delivery_version} is superseded"
            ) from exc
        raise
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
        workspace=workspace,
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
