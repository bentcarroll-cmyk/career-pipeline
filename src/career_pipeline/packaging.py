"""Deterministic, allowlisted packaging for the private beta."""

from __future__ import annotations

import hashlib
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .privacy import scan_tree


ARCHIVE_NAME = "career-pipeline-plugin.zip"
_FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_RUNTIME_TREES = (
    ".agents",
    ".codex-plugin",
    "schemas",
    "scripts",
    "skills",
    "src",
)
_RUNTIME_FILES = (
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "docs/beta-testing.md",
    "docs/private-beta-installation.md",
    "docs/private-beta-upgrades.md",
    "docs/releasing.md",
    "pyproject.toml",
)
_SKIP_PARTS = {"__pycache__", ".pytest_cache"}
_SKIP_SUFFIXES = {".pyc", ".pyo"}


class PackagingError(ValueError):
    pass


@dataclass(frozen=True)
class PackageResult:
    archive: Path
    checksum: Path
    sha256: str
    members: tuple[str, ...]


def _members(repository: Path) -> tuple[tuple[str, Path], ...]:
    selected: dict[str, Path] = {}
    for name in _RUNTIME_TREES:
        tree = repository / name
        if not tree.is_dir():
            raise PackagingError(f"required runtime directory is missing: {name}")
        for path in tree.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(repository)
            if any(part in _SKIP_PARTS for part in relative.parts):
                continue
            if path.suffix.lower() in _SKIP_SUFFIXES:
                continue
            if path.is_symlink():
                raise PackagingError(f"runtime package cannot contain symlinks: {relative}")
            selected[relative.as_posix()] = path
    for name in _RUNTIME_FILES:
        path = repository / name
        if not path.is_file():
            raise PackagingError(f"required runtime file is missing: {name}")
        if path.is_symlink():
            raise PackagingError(f"runtime package cannot contain symlinks: {name}")
        selected[name] = path
    return tuple(sorted(selected.items()))


def _mode(name: str) -> int:
    return 0o755 if name.startswith("scripts/") and name.endswith(".py") else 0o644


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_plugin_archive(repository: Path, output: Path) -> PackageResult:
    repository = repository.resolve()
    output = output.resolve()
    members = _members(repository)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / ARCHIVE_NAME
    with zipfile.ZipFile(
        archive,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as bundle:
        for name, source in members:
            info = zipfile.ZipInfo(name, date_time=_FIXED_TIMESTAMP)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | _mode(name)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, source.read_bytes(), compresslevel=9)
    findings = scan_tree(archive)
    if findings:
        archive.unlink(missing_ok=True)
        raise PackagingError("packaged archive failed the privacy scan")
    digest = _sha256(archive)
    checksum = output / f"{ARCHIVE_NAME}.sha256"
    checksum.write_text(f"{digest}  {ARCHIVE_NAME}\n", encoding="ascii")
    return PackageResult(
        archive=archive,
        checksum=checksum,
        sha256=digest,
        members=tuple(name for name, _ in members),
    )
