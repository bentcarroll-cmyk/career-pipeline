"""Small, deterministic validators for persisted Career Pipeline contracts."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
from datetime import date
from typing import Mapping

from .atomic import load_json
from .contracts import ValidationError


_SCHEMA_DIRECTORY = Path(__file__).resolve().parents[2] / "schemas"


def _error(code: str, path: str, message: str) -> ValidationError:
    return ValidationError(code=code, path=path, message=message)


def validate_document(
    schema_name: str,
    value: Mapping[str, object],
) -> list[ValidationError]:
    schema = _load_schema(schema_name)
    if schema is None:
        return [_error("unknown_schema", "$", f"unknown schema: {schema_name}")]
    errors = _validate_schema(schema, value, "$", schema)
    validators = {"config": _validate_config, "job": _validate_job}
    validator = validators.get(schema_name)
    if validator is not None:
        if schema_name == "job":
            custom_fields = {
                "$.schema_version",
                "$.job_id",
                "$.status",
                "$.disposition",
                "$.paths.posting",
                "$.paths.assessment",
                "$.paths.events",
                "$.paths.working",
            }
            errors = [error for error in errors if error.path not in custom_fields]
        errors = [
            error
            for error in errors
            if not (error.path == "$.schema_version" and error.code == "invalid_const")
        ]
        errors.extend(validator(value))
    return _unique_errors(errors)


def persisted_schema_names() -> tuple[str, ...]:
    """Return every packaged persisted JSON schema name."""
    return tuple(
        sorted(path.name.removesuffix(".schema.json") for path in _SCHEMA_DIRECTORY.glob("*.schema.json"))
    )


def validate_persisted_file(schema_name: str, path: Path) -> list[ValidationError]:
    """Validate a JSON document without including its contents in diagnostics."""
    try:
        value = load_json(path)
    except (OSError, ValueError):
        return [_error("unreadable", "$", "document could not be read")]
    if not isinstance(value, Mapping):
        return [_error("invalid_type", "$", "document must be an object")]
    return validate_document(schema_name, value)


def diagnose_workspace(root: Path) -> tuple[tuple[str, str], ...]:
    """Return content-free repair codes for known persisted workspace documents."""
    root = root.resolve()
    expected = (
        ("config", root / "State" / "config.json", True),
        ("onboarding-state", root / "State" / "onboarding-state.json", True),
        ("next-job-id", root / "State" / "next-job-id.json", True),
        ("discovery-state", root / "State" / "discovery-state.json", False),
        ("application-manifest", root / "State" / "application-manifest.json", False),
        ("search-criteria-approval", root / "State" / "search-criteria-approval.json", False),
        ("search-criteria", root / "Profile" / "Search_Criteria.json", False),
        ("backlog-index", root / "Indexes" / "backlog.json", False),
        ("deduplication-index", root / "Indexes" / "deduplication.json", False),
        ("actionable-backlog", root / "Indexes" / "actionable-backlog.json", False),
    )
    findings: list[tuple[str, str]] = []
    for schema_name, path, required in expected:
        if not path.exists():
            if required:
                findings.append((schema_name, "missing"))
            continue
        findings.extend(
            (schema_name, error.code)
            for error in validate_persisted_file(schema_name, path)
        )
    for job_path in sorted((root / "Jobs").glob("JOB-*/job.json")):
        job_errors = validate_persisted_file("job", job_path)
        findings.extend(("job", error.code) for error in job_errors)
        try:
            job = load_json(job_path)
        except (OSError, ValueError):
            job = {}
        exports = job.get("exports")
        if isinstance(exports, list):
            for receipt in exports:
                if not isinstance(receipt, Mapping):
                    findings.append(("export-receipt", "invalid_type"))
                else:
                    findings.extend(
                        ("export-receipt", error.code)
                        for error in validate_document("export-receipt", receipt)
                    )
        events_path = job_path.with_name("events.jsonl")
        if not events_path.is_file():
            findings.append(("job-event", "missing"))
        else:
            findings.extend(_diagnose_json_lines("job-event", events_path))
    persisted_runs = (
        ("discovery-run", root / "Runs" / "discovery", "run-*.json"),
        (
            "discovery-evidence-receipt",
            root / "Runs" / "discovery" / "sources",
            "receipt-*.json",
        ),
        ("lifecycle-receipt", root / "Runs" / "lifecycle", "receipt-*.json"),
    )
    for schema_name, directory, pattern in persisted_runs:
        for path in sorted(directory.glob(pattern)):
            findings.extend(
                (schema_name, error.code)
                for error in validate_persisted_file(schema_name, path)
            )
    return tuple(dict.fromkeys(findings))


def _diagnose_json_lines(
    schema_name: str,
    path: Path,
) -> tuple[tuple[str, str], ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ((schema_name, "unreadable"),)
    if not lines:
        return ((schema_name, "missing"),)
    findings: list[tuple[str, str]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            findings.append((schema_name, "unreadable"))
            continue
        if not isinstance(value, Mapping):
            findings.append((schema_name, "invalid_type"))
            continue
        findings.extend(
            (schema_name, error.code)
            for error in validate_document(schema_name, value)
        )
    return tuple(dict.fromkeys(findings))


def _load_schema(schema_name: str) -> Mapping[str, object] | None:
    path = _SCHEMA_DIRECTORY / f"{schema_name}.schema.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _unique_errors(errors: list[ValidationError]) -> list[ValidationError]:
    return list(dict.fromkeys(errors))


def _resolve(
    schema: Mapping[str, object], root: Mapping[str, object]
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema, root
    target_root = root
    fragment = ref
    if not ref.startswith("#"):
        filename, separator, fragment = ref.partition("#")
        if not filename.endswith(".schema.json"):
            return schema, root
        loaded = _load_schema(Path(filename).name.removesuffix(".schema.json"))
        if loaded is None:
            return schema, root
        target_root = loaded
        fragment = f"#{fragment}" if separator else "#"
    if fragment == "#":
        return target_root, target_root
    if not fragment.startswith("#/"):
        return schema, root
    current: object = target_root
    for part in fragment[2:].split("/"):
        if not isinstance(current, Mapping):
            return schema, root
        current = current.get(part)
    return (
        (current, target_root)
        if isinstance(current, Mapping)
        else (schema, root)
    )


def _type_matches(value: object, expected: str) -> bool:
    return {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, True)


def _json_equal(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    return left == right


def _validate_schema(
    schema: Mapping[str, object], value: object, path: str, root: Mapping[str, object]
) -> list[ValidationError]:
    schema, root = _resolve(schema, root)
    errors: list[ValidationError] = []
    expected_types = schema.get("type")
    if isinstance(expected_types, str):
        expected_types = [expected_types]
    if isinstance(expected_types, list) and not any(
        isinstance(item, str) and _type_matches(value, item) for item in expected_types
    ):
        return [_error("invalid_type", path, "value has an invalid type")]
    if "const" in schema and not _json_equal(value, schema["const"]):
        errors.append(_error("invalid_const", path, "value does not match the required constant"))
    options = schema.get("enum")
    if isinstance(options, list) and not any(
        _json_equal(value, option) for option in options
    ):
        errors.append(_error("invalid_enum", path, "value is not allowed"))
    if isinstance(value, str):
        if isinstance(schema.get("minLength"), int) and len(value) < schema["minLength"]:
            errors.append(_error("min_length", path, "string is too short"))
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            errors.append(_error("invalid_pattern", path, "string does not match the required pattern"))
        maximum = schema.get("maxLength")
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append(_error("max_length", path, "string is too long"))
        if schema.get("format") == "date":
            try:
                date.fromisoformat(value)
            except ValueError:
                errors.append(_error("invalid_format", path, "string has an invalid date format"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(_error("below_minimum", path, "number is too small"))
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(_error("above_maximum", path, "number is too large"))
    if isinstance(value, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(_error("min_items", path, "array has too few items"))
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append(_error("max_items", path, "array has too many items"))
        if schema.get("uniqueItems") is True and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            errors.append(_error("duplicate_item", path, "array items must be unique"))
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, item in enumerate(value):
                errors.extend(_validate_schema(items, item, f"{path}[{index}]", root))
    if isinstance(value, Mapping):
        required = schema.get("required")
        if isinstance(required, list):
            for name in required:
                if isinstance(name, str) and name not in value:
                    errors.append(_error("required_field", f"{path}.{name}", "field is required"))
        properties = schema.get("properties")
        property_map = properties if isinstance(properties, Mapping) else {}
        patterns = schema.get("patternProperties")
        pattern_map = patterns if isinstance(patterns, Mapping) else {}
        for name, item in value.items():
            item_path = f"{path}.{name}"
            child = property_map.get(name) if isinstance(name, str) else None
            if isinstance(child, Mapping):
                errors.extend(_validate_schema(child, item, item_path, root))
                continue
            matched = False
            for pattern, pattern_schema in pattern_map.items():
                if isinstance(pattern, str) and isinstance(pattern_schema, Mapping) and isinstance(name, str) and re.search(pattern, name):
                    errors.extend(_validate_schema(pattern_schema, item, item_path, root))
                    matched = True
            if matched:
                continue
            additional = schema.get("additionalProperties", True)
            if additional is False:
                errors.append(_error("unexpected_field", item_path, "field is not allowed"))
            elif isinstance(additional, Mapping):
                errors.extend(_validate_schema(additional, item, item_path, root))
    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for item in all_of:
            if isinstance(item, Mapping):
                errors.extend(_validate_schema(item, value, path, root))
    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        matches = sum(
            not _validate_schema(item, value, path, root)
            for item in one_of
            if isinstance(item, Mapping)
        )
        if matches != 1:
            errors.append(_error("one_of", path, "value must match exactly one allowed form"))
    condition = schema.get("if")
    if isinstance(condition, Mapping) and not _validate_schema(condition, value, path, root):
        then = schema.get("then")
        if isinstance(then, Mapping):
            errors.extend(_validate_schema(then, value, path, root))
    return errors


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
    if value.get("schema_version") != 2:
        errors.append(_error("schema_version", "schema_version", "must equal 2"))
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
_DISPOSITIONS = {"strong_match", "worth_considering", "non_match"}


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
        "source_record_id",
        "posting_url",
        "application_url",
        "source",
        "verified_at",
        "verification_status",
        "raw_field_hash",
        "role_to_profile_fit",
        "recommended_next_action",
        "discovered_at",
    ):
        if not isinstance(value.get(field), str) or not value.get(field):
            errors.append(_error("required_string", field, "must be a non-empty string"))
    raw_field_hash = value.get("raw_field_hash")
    if isinstance(raw_field_hash, str) and re.fullmatch(r"[a-f0-9]{64}", raw_field_hash) is None:
        errors.append(_error("content_hash", "raw_field_hash", "must be a SHA-256 hash"))
    for field in ("assessment_profile_hash", "assessment_criteria_hash"):
        item = value.get(field)
        if item is not None and (
            not isinstance(item, str) or re.fullmatch(r"[a-f0-9]{64}", item) is None
        ):
            errors.append(_error("content_hash", field, "must be a SHA-256 hash or null"))
    assessment_hash = value.get("assessment_hash")
    if assessment_hash is not None and (
        not isinstance(assessment_hash, str)
        or re.fullmatch(r"[a-f0-9]{64}", assessment_hash) is None
    ):
        errors.append(_error("content_hash", "assessment_hash", "must be a SHA-256 hash"))
    assessment_at = value.get("assessment_at")
    if assessment_at is not None and (
        not isinstance(assessment_at, str) or not assessment_at.strip()
    ):
        errors.append(_error("required_string", "assessment_at", "must be a timestamp"))
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
