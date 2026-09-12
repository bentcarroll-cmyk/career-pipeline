"""Fail-closed scanning for content that must not ship with the plugin."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str


_TEXT_RULES = {
    "credential-assignment": re.compile(
        r"(?i)(?:^|[\s,{])['\"]?(?:(?:[a-z0-9]+[_-])*)"
        r"(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
        r"['\"]?\s*[:=]\s*['\"]?[^\s'\"]+"
    ),
    "email-address": re.compile(
        r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
    ),
    "fixed-user-home": re.compile(
        r"(?:/Users/[^/\s]+|/home/[^/\s]+|[A-Za-z]:\\Users\\[^\\\s]+)"
    ),
    "private-url": re.compile(
        r"(?i)https?://(?:localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|"
        r"192\.168\.\d+\.\d+|[^/\s]+\.(?:local|internal))(?:[/\s]|$)"
    ),
    "telemetry-sdk": re.compile(
        r"(?i)(?:import\s+sentry_sdk|from\s+sentry_sdk|"
        r"segmentio|datadog|mixpanel|amplitude[_-]?analytics)"
    ),
}

_FORBIDDEN_SUFFIXES = {".doc", ".docx", ".pdf"}
_SKIP_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", ".superpowers"}
_USER_DATA_PARTS = {"Applications", "Profile", "Sources", "Runs", "State"}
_RULE_ALLOWLIST = {
    "src/career_pipeline/privacy.py": {"fixed-user-home", "telemetry-sdk"},
}
_SENSITIVE_SUFFIXES = {".key", ".keystore", ".pem", ".p12", ".pfx", ".jks"}
_SENSITIVE_NAMES = {
    ".credentials",
    ".env",
    ".secrets",
    "id_ed25519",
    "id_rsa",
}
_CREDENTIAL_BEARING_NAMES = re.compile(
    r"(?i)^(?:credentials?|secrets?|tokens?)(?:[._-]|$)"
)


def _scan_text(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in _TEXT_RULES.items():
            if rule not in _RULE_ALLOWLIST.get(path, set()) and pattern.search(line):
                findings.append(Finding(path, line_number, rule))
    return findings


def _relative_display(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _sensitive_file_rule(member: PurePosixPath) -> str | None:
    if member.name.lower() in _SENSITIVE_NAMES or member.suffix.lower() in _SENSITIVE_SUFFIXES:
        return "sensitive-file-name"
    if _CREDENTIAL_BEARING_NAMES.match(member.name):
        return "credential-bearing-file"
    return None


def _scan_paths(root: Path) -> Iterable[tuple[str, bytes]]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in _SKIP_PARTS for part in path.parts):
            continue
        relative = _relative_display(path, root)
        yield relative, path.read_bytes()


def _scan_members(archive: Path) -> Iterable[tuple[str, bytes]]:
    with zipfile.ZipFile(archive) as bundle:
        for name in sorted(bundle.namelist()):
            member = PurePosixPath(name)
            if name.endswith("/") or any(part in _SKIP_PARTS for part in member.parts):
                continue
            yield member.as_posix(), bundle.read(name)


def scan_tree(root: Path) -> list[Finding]:
    """Return privacy findings using relative member names only."""
    root = root.resolve()
    entries = _scan_members(root) if root.is_file() and zipfile.is_zipfile(root) else _scan_paths(root)
    findings: list[Finding] = []
    for relative, raw in entries:
        member = PurePosixPath(relative)
        if member.suffix.lower() in _FORBIDDEN_SUFFIXES:
            findings.append(Finding(relative, 0, "application-document"))
            continue
        if any(part in _USER_DATA_PARTS for part in member.parts):
            findings.append(Finding(relative, 0, "generated-user-data"))
            continue
        file_rule = _sensitive_file_rule(member)
        if b"\x00" in raw:
            if file_rule is not None:
                findings.append(Finding(relative, 0, file_rule))
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        text_findings = _scan_text(relative, text)
        findings.extend(text_findings)
        if file_rule is not None and not text_findings:
            findings.append(Finding(relative, 0, file_rule))
    return findings
