"""Small, deterministic validators for persisted Career Pipeline contracts."""

from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import Mapping

from .contracts import ValidationError


def _error(code: str, path: str, message: str) -> ValidationError:
    return ValidationError(code=code, path=path, message=message)


def validate_document(
    schema_name: str,
    value: Mapping[str, object],
) -> list[ValidationError]:
    validators = {
        "config": _validate_config,
        "job": _validate_job,
    }
    validator = validators.get(schema_name)
    if validator is None:
        return [_error("unknown_schema", "$", f"unknown schema: {schema_name}")]
    return validator(value)


def _relative_path_errors(
    paths: object,
    required: tuple[str, ...],
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not isinstance(paths, Mapping):
        return [_error("required_object", "paths", "must be an object")]
    for field in required:
        item = paths.get(field)
        field_path = f"paths.{field}"
        if not isinstance(item, str) or not item:
            errors.append(_error("required_string", field_path, "must be set"))
            continue
        parsed = PurePosixPath(item)
        if parsed.is_absolute() or ".." in parsed.parts:
            errors.append(_error("relative_path", field_path, "must be relative"))
    return errors


def _validate_config(value: Mapping[str, object]) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if value.get("schema_version") != 1:
        errors.append(_error("schema_version", "schema_version", "must equal 1"))
    for field in ("workspace_root", "timezone"):
        item = value.get(field)
        if not isinstance(item, str) or not item.strip():
            errors.append(_error("required_string", field, "must be a non-empty string"))
    errors.extend(
        _relative_path_errors(
            value.get("paths"),
            (
                "profile",
                "sources",
                "jobs",
                "applications",
                "indexes",
                "runs",
                "state",
            ),
        )
    )
    return errors


_JOB_ID = re.compile(r"JOB-[0-9]{6}")
_JOB_STATUSES = {
    "new",
    "needs_confirmation",
    "prepare_application",
    "packet_ready",
    "applied",
    "interviewing",
    "offer",
    "not_pursuing",
    "closed",
}
_DISPOSITIONS = {"strong_match", "worth_considering"}


def _validate_job(value: Mapping[str, object]) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if value.get("schema_version") != 1:
        errors.append(_error("schema_version", "schema_version", "must equal 1"))
    job_id = value.get("job_id")
    if not isinstance(job_id, str) or _JOB_ID.fullmatch(job_id) is None:
        errors.append(_error("job_id", "job_id", "must match JOB-000000"))
    for field in (
        "employer",
        "title",
        "posting_url",
        "application_url",
        "source",
        "verified_at",
        "role_to_profile_fit",
        "recommended_next_action",
        "discovered_at",
    ):
        if not isinstance(value.get(field), str) or not value.get(field):
            errors.append(_error("required_string", field, "must be a non-empty string"))
    if value.get("disposition") not in _DISPOSITIONS:
        errors.append(
            _error("job_disposition", "disposition", "must be a qualifying disposition")
        )
    if value.get("status") not in _JOB_STATUSES:
        errors.append(_error("job_status", "status", "must be a supported status"))
    for field in ("strengths", "gaps", "uncertainties", "application_versions", "exports"):
        if not isinstance(value.get(field), list):
            errors.append(_error("required_array", field, "must be an array"))
    job_paths = value.get("paths")
    required_paths = ("posting", "assessment", "events", "working")
    errors.extend(_relative_path_errors(job_paths, required_paths))
    if isinstance(job_id, str) and _JOB_ID.fullmatch(job_id) and isinstance(job_paths, Mapping):
        expected_prefix = ("Jobs", job_id)
        for field in required_paths:
            item = job_paths.get(field)
            if not isinstance(item, str):
                continue
            parsed = PurePosixPath(item)
            if tuple(parsed.parts[:2]) != expected_prefix:
                errors.append(
                    _error(
                        "job_path_mismatch",
                        f"paths.{field}",
                        "must point into the canonical job folder",
                    )
                )
    return errors
