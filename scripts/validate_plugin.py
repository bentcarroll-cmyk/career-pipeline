#!/usr/bin/env python3
"""Validate the repository's Codex plugin shell without third-party packages."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
SKILL_NAMES = {"onboard", "discover-jobs", "review-backlog", "prepare-application"}


def validate_manifest(root: Path) -> list[str]:
    errors: list[str] = []
    path = root / ".codex-plugin" / "plugin.json"
    if not path.is_file():
        return ["missing .codex-plugin/plugin.json"]
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid plugin manifest: {exc}"]

    if manifest.get("name") != "career-pipeline":
        errors.append("manifest name must be career-pipeline")
    if not isinstance(manifest.get("version"), str) or not SEMVER.fullmatch(manifest["version"]):
        errors.append("manifest version must be strict semver")
    if manifest.get("skills") != "./skills/":
        errors.append("manifest skills must be ./skills/")
    for unsupported in ("apps", "mcpServers", "hooks"):
        if unsupported in manifest:
            errors.append(f"manifest must not declare {unsupported}")
    author = manifest.get("author")
    if not isinstance(author, dict) or not author.get("name"):
        errors.append("manifest author.name is required")
    interface = manifest.get("interface")
    for field in (
        "displayName",
        "shortDescription",
        "longDescription",
        "developerName",
        "category",
        "capabilities",
        "defaultPrompt",
    ):
        if not isinstance(interface, dict) or not interface.get(field):
            errors.append(f"manifest interface.{field} is required")
    if isinstance(interface, dict):
        prompts = interface.get("defaultPrompt", [])
        if not isinstance(prompts, list) or len(prompts) > 3:
            errors.append("manifest defaultPrompt must contain at most three entries")

    discovered = {
        path.parent.name for path in (root / "skills").glob("*/SKILL.md")
    }
    if discovered != SKILL_NAMES:
        errors.append(f"expected skills {sorted(SKILL_NAMES)}, found {sorted(discovered)}")
    for skill_name in sorted(discovered):
        text = (root / "skills" / skill_name / "SKILL.md").read_text(encoding="utf-8")
        if not text.startswith("---\n") or f"name: {skill_name}\n" not in text:
            errors.append(f"{skill_name}: invalid SKILL.md frontmatter")
        if "[TODO:" in text:
            errors.append(f"{skill_name}: unfinished scaffold marker")
    return errors


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) == 2 else Path(__file__).resolve().parents[1]
    errors = validate_manifest(root)
    for error in errors:
        print(error)
    if errors:
        return 1
    print("plugin validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
