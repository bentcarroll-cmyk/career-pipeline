"""Safe creation and use of a user-approved Career Pipeline workspace."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from .atomic import atomic_write_json, load_json
from .contracts import SourceReceipt, WorkspacePaths


class WorkspaceError(ValueError):
    pass


_DIRECTORIES = (
    "Profile",
    "Sources",
    "Sources/connector-source-notes",
    "Jobs",
    "Applications",
    "Indexes",
    "Runs",
    "Runs/discovery",
    "Runs/lifecycle",
    "State",
)
_SOURCE_RESUME_RECEIPT = "source-resume-receipt.json"
_SHA256 = re.compile(r"[a-f0-9]{64}")


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def workspace_paths(root: Path) -> WorkspacePaths:
    """Resolve workspace paths without creating or changing anything."""
    resolved = root.expanduser().resolve()
    return WorkspacePaths(
        root=resolved,
        profile=resolved / "Profile",
        sources=resolved / "Sources",
        jobs=resolved / "Jobs",
        applications=resolved / "Applications",
        indexes=resolved / "Indexes",
        runs=resolved / "Runs",
        state=resolved / "State",
    )


def create_workspace(
    root: Path,
    repository_root: Path | None = None,
) -> WorkspacePaths:
    paths = workspace_paths(root)
    resolved = paths.root
    if repository_root is not None and _contains(repository_root.resolve(), resolved):
        raise WorkspaceError("workspace root must be outside the plugin repository")
    for relative in _DIRECTORIES:
        (resolved / relative).mkdir(parents=True, exist_ok=True)
    next_job_id = resolved / "State" / "next-job-id.json"
    if not next_job_id.exists():
        atomic_write_json(
            next_job_id,
            {"schema_version": 1, "next_id": 1},
        )
    return paths


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_receipt_mapping(receipt: SourceReceipt, paths: WorkspacePaths) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_name": receipt.source_name,
        "destination": receipt.destination.relative_to(paths.root).as_posix(),
        "size": receipt.size,
        "sha256": receipt.sha256,
    }


def save_source_resume_receipt(receipt: SourceReceipt, paths: WorkspacePaths) -> None:
    """Atomically persist the immutable receipt for the preserved source resume."""
    atomic_write_json(
        paths.state / _SOURCE_RESUME_RECEIPT,
        _source_receipt_mapping(receipt, paths),
    )


def load_source_resume_receipt(paths: WorkspacePaths) -> SourceReceipt:
    """Load a validated source-resume receipt without trusting arbitrary paths."""
    raw = load_json(paths.state / _SOURCE_RESUME_RECEIPT)
    destination = raw.get("destination")
    size = raw.get("size")
    sha256 = raw.get("sha256")
    source_name = raw.get("source_name")
    if (
        raw.get("schema_version") != 1
        or not isinstance(destination, str)
        or Path(destination).is_absolute()
        or ".." in Path(destination).parts
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
        or not isinstance(sha256, str)
        or _SHA256.fullmatch(sha256) is None
        or not isinstance(source_name, str)
        or not source_name
    ):
        raise WorkspaceError("source resume receipt is invalid")
    destination_path = paths.root / destination
    resolved = destination_path.resolve()
    try:
        resolved.relative_to(paths.sources)
    except ValueError as exc:
        raise WorkspaceError("source resume receipt is outside Sources") from exc
    return SourceReceipt(
        source_name=source_name,
        destination=destination_path,
        size=size,
        sha256=sha256,
    )


def preserve_source_resume(source: Path, paths: WorkspacePaths) -> SourceReceipt:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise WorkspaceError("source resume must be a readable file")
    suffix = source.suffix
    destination = paths.sources / f"Resume_Original{suffix}"
    source_hash = _sha256(source)
    if destination.exists():
        if _sha256(destination) != source_hash:
            raise WorkspaceError("a different original resume is already preserved")
    else:
        shutil.copy2(source, destination)
        if _sha256(destination) != source_hash:
            destination.unlink(missing_ok=True)
            raise WorkspaceError("preserved resume hash did not match the source")
    receipt = SourceReceipt(
        source_name=source.name,
        destination=destination,
        size=destination.stat().st_size,
        sha256=source_hash,
    )
    receipt_path = paths.state / _SOURCE_RESUME_RECEIPT
    if receipt_path.exists():
        if load_source_resume_receipt(paths) != receipt:
            raise WorkspaceError("persisted source resume receipt does not match the source")
    else:
        save_source_resume_receipt(receipt, paths)
    return receipt
