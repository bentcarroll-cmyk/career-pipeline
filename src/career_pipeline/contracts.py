"""Shared immutable contracts for deterministic plugin helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    profile: Path
    sources: Path
    applications: Path
    runs: Path
    state: Path


@dataclass(frozen=True)
class SourceReceipt:
    source_name: str
    destination: Path
    size: int
    sha256: str


@dataclass(frozen=True)
class ValidationError:
    code: str
    path: str
    message: str


JsonObject = dict[str, Any]
