"""Small, deterministic validators for persisted Career Pipeline contracts."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Mapping

from .contracts import ValidationError


def _error(code: str, path: str, message: str) -> ValidationError:
    return ValidationError(code=code, path=path, message=message)


def validate_document(
    schema_name: str,
    value: Mapping[str, object],
) -> list[ValidationError]:
    if schema_name != "config":
        return [_error("unknown_schema", "$", f"unknown schema: {schema_name}")]
    errors: list[ValidationError] = []
    if value.get("schema_version") != 1:
        errors.append(_error("schema_version", "schema_version", "must equal 1"))
    for field in ("workspace_root", "timezone"):
        item = value.get(field)
        if not isinstance(item, str) or not item.strip():
            errors.append(_error("required_string", field, "must be a non-empty string"))
    paths = value.get("paths")
    if not isinstance(paths, Mapping):
        errors.append(_error("required_object", "paths", "must be an object"))
    else:
        for field in ("profile", "sources", "applications", "runs", "state"):
            item = paths.get(field)
            if not isinstance(item, str) or not item:
                errors.append(_error("required_string", f"paths.{field}", "must be set"))
            elif PurePosixPath(item).is_absolute() or ".." in PurePosixPath(item).parts:
                errors.append(_error("relative_path", f"paths.{field}", "must be relative"))
    linear = value.get("linear")
    if not isinstance(linear, Mapping):
        errors.append(_error("required_object", "linear", "must be an object"))
    else:
        for field in ("workspace_id", "team_id"):
            if not isinstance(linear.get(field), str) or not linear.get(field):
                errors.append(_error("required_string", f"linear.{field}", "must be set"))
    return errors
