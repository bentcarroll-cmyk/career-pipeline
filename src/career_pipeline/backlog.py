"""Canonical backlog actions with validated auxiliary packet progress."""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from .atomic import atomic_write_json, load_json
from .contracts import WorkspacePaths
from .indexes import load_indexes
from .job_store import JobStoreError, read_job, update_job_status, workspace_lock
from .packets import STAGES as PACKET_STAGES
from .packets import (
    InvalidPacketTransition,
    PacketRecord,
    load_manifest,
    resume_queue,
    validate_manifest_contract,
    validate_packet_history,
)
from .timestamps import TimestampError, parse_instant


class SelectionError(ValueError):
    pass


@dataclass(frozen=True)
class PacketSelection:
    job_ids: tuple[str, ...]
    per_role_instructions: Mapping[str, str]

    @property
    def ticket_ids(self) -> tuple[str, ...]:
        return self.job_ids


_JOB_DIR = re.compile(r"JOB-[0-9]{6}")
_INACTIVE_STATUSES = frozenset({"not_pursuing", "closed"})
_LIFECYCLE_PRIORITY = {
    "offer": 900,
    "interviewing": 800,
    "applied": 700,
    "prepare_application": 600,
    "packet_ready": 500,
    "needs_confirmation": 400,
    "new": 300,
}
_DISPOSITION_PRIORITY = {"strong_match": 2, "worth_considering": 1, "non_match": 0}


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


def _source_hash(records: Sequence[tuple[Mapping[str, object], str]]) -> str:
    digest = hashlib.sha256()
    for record, record_hash in records:
        digest.update(str(record["job_id"]).encode("utf-8"))
        digest.update(b"\x00")
        digest.update(record_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _view_source_hash(
    records: Sequence[tuple[Mapping[str, object], str]],
    packet_manifest_hash: str | None,
) -> str:
    digest = hashlib.sha256()
    digest.update(_source_hash(records).encode("ascii"))
    digest.update(b"\npacket-manifest\x00")
    digest.update(
        packet_manifest_hash.encode("ascii")
        if packet_manifest_hash is not None
        else b"none"
    )
    return digest.hexdigest()


def _packet_paths_are_bound(record: PacketRecord) -> bool:
    version_parts = record.version_dir.parts
    return (
        len(version_parts) == 3
        and version_parts[0] == "Applications"
        and version_parts[1].startswith(f"{record.job_id}_")
        and version_parts[2] == record.version
        and record.resume_pdf.parent == record.version_dir
        and (
            record.cover_letter_pdf is None
            or record.cover_letter_pdf.parent == record.version_dir
        )
        and record.working_dir == record.version_dir / "working"
    )


def _load_packet_progress_locked(
    workspace: WorkspacePaths,
    canonical: Sequence[tuple[Mapping[str, object], str]],
) -> tuple[dict[str, PacketRecord], str | None]:
    manifest_path = workspace.state / "application-manifest.json"
    if manifest_path.is_symlink():
        raise SelectionError("application manifest is invalid")
    if not manifest_path.exists():
        return {}, None
    if not manifest_path.is_file():
        raise SelectionError("application manifest is invalid")
    try:
        manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        validate_manifest_contract(load_json(manifest_path))
        manifest = load_manifest(manifest_path)
    except (
        AttributeError,
        InvalidPacketTransition,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        raise SelectionError("application manifest is invalid") from exc
    canonical_by_id = {str(record["job_id"]): record for record, _ in canonical}
    if manifest.schema_version != 1:
        raise SelectionError("application manifest is invalid")
    for job_id, records in manifest.packets.items():
        if (
            not isinstance(job_id, str)
            or _JOB_DIR.fullmatch(job_id) is None
            or job_id not in canonical_by_id
        ):
            raise SelectionError("application manifest is not bound to a canonical job")
        prior_version = 0
        for record in records:
            if (
                record.job_id != job_id
                or not isinstance(record.employer, str)
                or not record.employer
                or not isinstance(record.title, str)
                or not record.title
                or re.fullmatch(r"v[0-9]{3}", record.version) is None
                or record.stage not in PACKET_STAGES
                or not _packet_paths_are_bound(record)
            ):
                raise SelectionError("application manifest is not bound to a canonical job")
            version = int(record.version[1:])
            if version <= prior_version:
                raise SelectionError("application manifest packet versions are invalid")
            prior_version = version
            try:
                validate_packet_history(record)
            except InvalidPacketTransition as exc:
                raise SelectionError(
                    "application manifest receipt history is invalid"
                ) from exc
            if record.stage == "ready":
                canonical_versions = canonical_by_id[job_id].get(
                    "application_versions", ()
                )
                if not isinstance(canonical_versions, list) or not any(
                    isinstance(item, Mapping)
                    and item.get("version") == record.version
                    for item in canonical_versions
                ):
                    raise SelectionError(
                        "application manifest ready packet is not canonical"
                    )
    return (
        {record.job_id: record for record in resume_queue(manifest)},
        manifest_hash,
    )


def _first_fact(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    return next(
        (item for item in value if isinstance(item, str) and item.strip()),
        None,
    )


def _facts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _deadline_factor(value: object, *, as_of: datetime) -> tuple[int, str | None]:
    if not isinstance(value, str) or not value.strip():
        return 0, None
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            days = (date.fromisoformat(value) - as_of.date()).days
        except ValueError:
            return 0, None
        if days < 0:
            return 4, "overdue"
        seconds_until_deadline = days * 24 * 60 * 60
    else:
        try:
            deadline = parse_instant(value)
        except TimestampError:
            return 0, None
        seconds_until_deadline = (deadline - as_of).total_seconds()
        if seconds_until_deadline <= 0:
            return 4, "overdue"
    if seconds_until_deadline <= 3 * 24 * 60 * 60:
        return 3, "within_3_days"
    if seconds_until_deadline <= 7 * 24 * 60 * 60:
        return 2, "within_7_days"
    if seconds_until_deadline <= 14 * 24 * 60 * 60:
        return 1, "within_14_days"
    return 0, None


def _freshness_sort_value(record: Mapping[str, object]) -> float:
    value = record.get("reverified_at") or record.get("verified_at")
    try:
        return parse_instant(str(value)).timestamp()
    except (TimestampError, ValueError, TypeError):
        return 0.0


def _recommended_action(
    record: Mapping[str, object],
    *,
    deadline_urgency: str | None,
    confirmation: str | None,
) -> str:
    status = record["status"]
    decisions = {
        "offer": "Review the recorded offer and decide the next user action.",
        "interviewing": "Prepare for the active interview process.",
        "applied": "Monitor the application for verified lifecycle evidence.",
        "prepare_application": (
            "Resume or explicitly restart the interrupted application packet."
        ),
        "packet_ready": "Review the ready packet and decide whether to submit it.",
    }
    if status in decisions:
        return decisions[str(status)]
    if deadline_urgency == "overdue":
        return "Verify whether this role remains open before deciding next steps."
    if status == "needs_confirmation" and confirmation is not None:
        return "Resolve the recorded fact needing confirmation."
    if deadline_urgency is not None:
        return "Review this role before its recorded deadline."
    return str(record["recommended_next_action"])


def build_actionable_backlog(
    workspace: WorkspacePaths,
    *,
    as_of: str,
) -> dict[str, object]:
    """Build a canonical-job view with validated packet progress as a follow-up."""

    try:
        as_of_instant = parse_instant(as_of)
    except TimestampError as exc:
        raise ValueError("as_of must be an ISO 8601 timestamp with a timezone") from exc
    with workspace_lock(workspace):
        canonical = _canonical_records(workspace)
        packet_progress, packet_manifest_hash = _load_packet_progress_locked(
            workspace, canonical
        )
        ranked: list[tuple[tuple[object, ...], dict[str, object]]] = []
        for record, record_hash in canonical:
            status = str(record["status"])
            if status in _INACTIVE_STATUSES:
                continue
            deadline_priority, deadline_urgency = _deadline_factor(
                record.get("deadline"), as_of=as_of_instant
            )
            confirmation = _first_fact(record.get("uncertainties"))
            confirmations = _facts(record.get("uncertainties"))
            major_gap = _first_fact(record.get("gaps"))
            packet = packet_progress.get(str(record["job_id"]))
            interrupted = packet is not None or status == "prepare_application"
            factors = {
                "lifecycle_status": status,
                "lifecycle_priority": _LIFECYCLE_PRIORITY[status],
                "deadline_urgency": deadline_urgency,
                "deadline_priority": deadline_priority,
                "needs_confirmation": (
                    status == "needs_confirmation" or bool(confirmations)
                ),
                "interrupted_packet": interrupted,
                "disposition_priority": _DISPOSITION_PRIORITY[
                    str(record["disposition"])
                ],
            }
            item = {
                "job_id": record["job_id"],
                "employer": record["employer"],
                "title": record["title"],
                "status": status,
                "disposition": record["disposition"],
                "fit_reason": record["role_to_profile_fit"],
                "major_gap": major_gap,
                "facts_needing_confirmation": confirmations,
                "source_freshness": {
                    "verified_at": record.get("verified_at"),
                    "reverified_at": record.get("reverified_at"),
                },
                "deadline": record.get("deadline"),
                "packet_stage": packet.stage if packet is not None else None,
                "packet_version": packet.version if packet is not None else None,
                "packet_next_action": (
                    "Resume or explicitly restart the interrupted application packet."
                    if interrupted
                    else None
                ),
                "recommended_next_action": _recommended_action(
                    record,
                    deadline_urgency=deadline_urgency,
                    confirmation=confirmation,
                ),
                "ranking_factors": factors,
                "record_hash": record_hash,
            }
            sort_key = (
                -int(factors["lifecycle_priority"]),
                -int(interrupted),
                -deadline_priority,
                -int(bool(factors["needs_confirmation"])),
                -int(factors["disposition_priority"]),
                -_freshness_sort_value(record),
                str(record["job_id"]),
            )
            ranked.append((sort_key, item))
        ranked.sort(key=lambda pair: pair[0])
        actions: list[dict[str, object]] = []
        for rank, (_, item) in enumerate(ranked, start=1):
            actions.append({"rank": rank, **item})
        view = {
            "schema_version": 1,
            "as_of": as_of_instant.isoformat().replace("+00:00", "Z"),
            "source_hash": _view_source_hash(canonical, packet_manifest_hash),
            "packet_manifest_hash": packet_manifest_hash,
            "ranking_policy": {
                "factor_order": [
                    "lifecycle_priority",
                    "interrupted_packet",
                    "deadline_priority",
                    "needs_confirmation",
                    "disposition_priority",
                    "source_freshness",
                    "job_id",
                ],
                "inactive_statuses": sorted(_INACTIVE_STATUSES),
                "lifecycle_priorities": dict(_LIFECYCLE_PRIORITY),
                "deadline_windows_days": [0, 3, 7, 14],
            },
            "actions": actions,
        }
        atomic_write_json(workspace.indexes / "actionable-backlog.json", view)
        return view


def render_actionable_backlog(view: Mapping[str, object]) -> str:
    actions = view.get("actions")
    if not isinstance(actions, list):
        raise ValueError("actionable backlog is invalid")
    lines = [f"Actionable backlog as of {view.get('as_of')}"]
    if not actions:
        return "\n".join((*lines, "No active roles."))
    for raw in actions:
        if not isinstance(raw, Mapping):
            raise ValueError("actionable backlog is invalid")
        freshness = raw.get("source_freshness")
        factors = raw.get("ranking_factors")
        if not isinstance(freshness, Mapping) or not isinstance(factors, Mapping):
            raise ValueError("actionable backlog is invalid")
        lines.extend(
            (
                f"{raw['rank']}. {raw['job_id']} — {raw['employer']} — {raw['title']}",
                f"   Status: {raw['status']} | Disposition: {raw['disposition']}",
                f"   Fit: {raw['fit_reason']}",
                f"   Major gap: {raw.get('major_gap') or 'unknown'}",
                (
                    "   Confirm: "
                    + (
                        "; ".join(raw.get("facts_needing_confirmation", ()))
                        if raw.get("facts_needing_confirmation")
                        else "unknown"
                    )
                ),
                (
                    "   Source freshness: verified "
                    f"{freshness.get('verified_at') or 'unknown'}; reverified "
                    f"{freshness.get('reverified_at') or 'unknown'}"
                ),
                f"   Deadline: {raw.get('deadline') or 'unknown'}",
                f"   Next: {raw['recommended_next_action']}",
                *(
                    (f"   Packet: {raw['packet_next_action']}",)
                    if raw.get("packet_next_action")
                    else ()
                ),
                (
                    "   Ranking: lifecycle="
                    f"{factors.get('lifecycle_priority')}, deadline="
                    f"{factors.get('deadline_priority')}, confirmation="
                    f"{str(bool(factors.get('needs_confirmation'))).lower()}"
                ),
            )
        )
    return "\n".join(lines)


def selection_from_request(
    job_ids: Sequence[str],
    per_role_instructions: Mapping[str, str],
    *,
    explicit_request: bool,
    workspace: WorkspacePaths,
) -> PacketSelection:
    if not explicit_request:
        raise SelectionError("packet preparation requires an explicit current request")
    ordered = tuple(dict.fromkeys(job.strip() for job in job_ids if job.strip()))
    if not ordered:
        raise SelectionError("at least one exact ticket ID is required")
    unknown = set(per_role_instructions).difference(ordered)
    if unknown:
        raise SelectionError("role instructions reference an unselected job")
    try:
        for job_id in ordered:
            read_job(workspace, job_id)
    except JobStoreError as exc:
        raise SelectionError("every selected job must exist in the canonical store") from exc
    return PacketSelection(ordered, dict(per_role_instructions))


def compare_jobs(
    workspace: WorkspacePaths,
    job_ids: Sequence[str],
) -> tuple[dict[str, object], ...]:
    ordered = tuple(dict.fromkeys(job_ids))
    return tuple(read_job(workspace, job_id) for job_id in ordered)


def mark_not_pursuing(
    workspace: WorkspacePaths,
    job_id: str,
    *,
    occurred_at: str,
) -> dict[str, object]:
    updated = update_job_status(
        workspace,
        job_id,
        "not_pursuing",
        occurred_at=occurred_at,
    )
    load_indexes(workspace)
    return updated
