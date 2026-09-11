"""Explicit, optional export receipts that never control canonical local state."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from .contracts import WorkspacePaths
from .indexes import load_indexes
from .job_store import record_export_receipt


class ExportRequestError(ValueError):
    pass


@dataclass(frozen=True)
class ExportReceipt:
    destination_kind: str
    destination_id: str
    job_id: str
    exported_at: str
    content_hash: str
    artifact_hashes: Mapping[str, str]
    verified: bool

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)


def record_verified_export(
    workspace: WorkspacePaths,
    job_id: str,
    receipt: ExportReceipt,
    *,
    explicit_request: bool,
) -> dict[str, object]:
    if not explicit_request:
        raise ExportRequestError("export requires a current explicit user request")
    if receipt.job_id != job_id:
        raise ExportRequestError("export receipt job does not match the canonical job")
    if not receipt.verified:
        raise ExportRequestError("only verified export readback may be recorded")
    updated = record_export_receipt(workspace, job_id, receipt.to_mapping())
    load_indexes(workspace)
    return updated
