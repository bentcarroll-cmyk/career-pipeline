#!/usr/bin/env python3
"""Read-only preflight; check runs on Python 3.9+, runtime needs 3.11+ and POSIX."""

from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import shutil
import sys


PLUGIN_NAME = "career-pipeline"
MARKETPLACE_NAME = "career-pipeline-private-beta"
SEMVER = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")


def check_package(root: Path) -> str:
    """Validate release identity and runtime presence without executing package code."""
    import tomllib  # Available only after main checks for Python 3.11+.

    for name in (
        ".codex-plugin/plugin.json",
        ".agents/plugins/marketplace.json",
        "pyproject.toml",
        "src/career_pipeline/__init__.py",
        "src/career_pipeline/workspace.py",
        "src/career_pipeline/schema.py",
    ):
        if not (root / name).is_file():
            raise ValueError(f"Missing package file: {root / name}. Extract the complete release archive.")

    manifest = json.loads((root / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads((root / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")).get("project", {})
    if not isinstance(manifest, dict) or manifest.get("name") != PLUGIN_NAME:
        raise ValueError(f"Plugin identifier must be {PLUGIN_NAME}.")
    if not isinstance(project, dict) or project.get("name") != PLUGIN_NAME:
        raise ValueError(f"Python package identifier must be {PLUGIN_NAME}.")
    if not isinstance(marketplace, dict) or marketplace.get("name") != MARKETPLACE_NAME:
        raise ValueError(f"Marketplace identifier must be {MARKETPLACE_NAME}.")
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list) or len(plugins) != 1 or not isinstance(plugins[0], dict):
        raise ValueError("Marketplace must contain the Career Pipeline plugin entry.")
    if plugins[0].get("name") != PLUGIN_NAME or plugins[0].get("source") != {"source": "local", "path": "./"}:
        raise ValueError("Marketplace must point to the local career-pipeline plugin at ./.")

    version = manifest.get("version")
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        raise ValueError("Plugin version must be semantic version text.")
    initializer = ast.parse((root / "src/career_pipeline/__init__.py").read_text(encoding="utf-8"))
    package_versions = [
        node.value.value
        for node in initializer.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
        and isinstance(node.value, ast.Constant)
    ]
    if project.get("version") != version or package_versions != [version]:
        raise ValueError("Release version mismatch across plugin.json, pyproject.toml, and package __version__.")
    if project.get("requires-python") != ">=3.11":
        raise ValueError("Package Python requirement must be >=3.11.")
    return version


def find_codex() -> str | None:
    executable = shutil.which("codex")
    if executable:
        return executable
    for applications in (Path("/Applications"), Path.home() / "Applications"):
        for application in ("Codex.app", "ChatGPT.app"):
            candidate = applications / application / "Contents/Resources/codex"
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", nargs="?", type=Path, default=Path(__file__).resolve().parents[1], help="extracted plugin directory (defaults to this script's package)")
    args = parser.parse_args()
    print(f"Python {'.'.join(map(str, sys.version_info[:3]))}: {sys.executable}")
    if sys.version_info < (3, 11):
        print("FAIL: Career Pipeline requires Python 3.11 or newer. Ask Codex Desktop to locate its supported Python runtime, or choose an available Python 3.11+ interpreter, then rerun this check with it.")
        return 1
    if os.name != "posix":
        print("FAIL: Career Pipeline requires POSIX file locking. Native Windows is unsupported; use Codex Desktop on macOS for this beta.")
        return 1
    try:
        from fcntl import flock  # Check availability without acquiring a lock.
    except (ImportError, OSError):
        print("FAIL: This Python runtime is missing fcntl.flock, required for workspace locking. Use a Python 3.11+ runtime with POSIX locking on macOS for this beta.")
        return 1
    print(f"Platform {sys.platform}: POSIX locking available. Local runtime checks are validated on macOS; Linux is unvalidated.")

    try:
        root = args.package.resolve()
        version = check_package(root)
    except (OSError, UnicodeError, ValueError, SyntaxError, ImportError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"PASS: {PLUGIN_NAME} {version}; marketplace {MARKETPLACE_NAME}; package {root}")
    codex = find_codex()
    if codex:
        print(f"Codex CLI executable found: {codex}")
    else:
        print("NOTE: Codex CLI was not found on PATH or in the usual macOS app locations. Ask Codex Desktop to locate its bundled CLI, or follow docs/private-beta-installation.md. This does not fail the Python/package check.")
    print("Preflight passed. Plugin registration, account access, and the Desktop workflow still need verification.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
