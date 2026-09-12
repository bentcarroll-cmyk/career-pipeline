import json
import tempfile
import unittest
from pathlib import Path

from career_pipeline.schema import (
    persisted_schema_names,
    validate_document,
    validate_persisted_file,
)


class SchemaTests(unittest.TestCase):
    def test_every_persisted_schema_has_a_runtime_validator(self) -> None:
        schema_directory = Path(__file__).resolve().parents[2] / "schemas"
        expected = {path.stem.removesuffix(".schema") for path in schema_directory.glob("*.schema.json")}

        self.assertEqual(set(persisted_schema_names()), expected)

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "synthetic.json"
            path.write_text(json.dumps({}), encoding="utf-8")
            for schema_name in persisted_schema_names():
                errors = validate_persisted_file(schema_name, path)
                self.assertTrue(errors, schema_name)
                self.assertNotIn(
                    "unknown_schema", {error.code for error in errors}, schema_name
                )

    def test_config_matches_required_fields_and_rejects_unexpected_fields(self) -> None:
        valid = {
            "schema_version": 2,
            "workspace_root": "/approved-at-runtime",
            "timezone": "America/New_York",
            "paths": {
                "profile": "Profile",
                "sources": "Sources",
                "jobs": "Jobs",
                "applications": "Applications",
                "indexes": "Indexes",
                "runs": "Runs",
                "state": "State",
            },
            "profile_approved": True,
            "criteria_approved": True,
            "connectors": {},
            "enabled_sources": ["public_ats"],
            "discovery_schedule": {
                "frequency": "weekday",
                "weekdays": ["MO"],
                "runs_per_day": 1,
                "timezone": "America/New_York",
            },
            "packet_defaults": {
                "resume_pages": 2,
                "cover_letter_enabled": True,
                "cover_letter_pages": 1,
            },
        }
        self.assertEqual(validate_document("config", valid), [])

        missing = dict(valid)
        missing.pop("enabled_sources")
        unexpected = {**valid, "private_marker": "synthetic-private-value"}
        self.assertIn(
            "required_field",
            {error.code for error in validate_document("config", missing)},
        )
        self.assertIn(
            "unexpected_field",
            {error.code for error in validate_document("config", unexpected)},
        )
    def test_config_requires_timezone_and_relative_subpaths(self) -> None:
        valid = {
            "schema_version": 2,
            "workspace_root": "/approved-at-runtime",
            "timezone": "America/New_York",
            "paths": {
                "profile": "Profile",
                "sources": "Sources",
                "jobs": "Jobs",
                "applications": "Applications",
                "indexes": "Indexes",
                "runs": "Runs",
                "state": "State",
            },
            "profile_approved": False,
            "criteria_approved": False,
            "connectors": {},
            "enabled_sources": ["public_ats"],
            "discovery_schedule": {
                "frequency": "weekday",
                "weekdays": ["MO"],
                "runs_per_day": 1,
                "timezone": "America/New_York",
            },
            "packet_defaults": {
                "resume_pages": 2,
                "cover_letter_enabled": True,
                "cover_letter_pages": 1,
            },
        }
        self.assertEqual(validate_document("config", valid), [])

        invalid = {**valid, "timezone": "", "paths": {**valid["paths"], "state": "/fixed"}}
        codes = {error.code for error in validate_document("config", invalid)}
        self.assertEqual(codes, {"min_length", "required_string", "relative_path"})

    def test_linear_is_optional_configuration(self) -> None:
        valid = {
            "schema_version": 2,
            "workspace_root": "/approved-at-runtime",
            "timezone": "America/New_York",
            "paths": {
                "profile": "Profile",
                "sources": "Sources",
                "jobs": "Jobs",
                "applications": "Applications",
                "indexes": "Indexes",
                "runs": "Runs",
                "state": "State",
            },
            "profile_approved": True,
            "criteria_approved": True,
            "connectors": {"linear": {"decision": "declined"}},
            "enabled_sources": ["public_ats"],
            "discovery_schedule": {
                "frequency": "weekday",
                "weekdays": ["MO"],
                "runs_per_day": 1,
                "timezone": "America/New_York",
            },
            "packet_defaults": {
                "resume_pages": 2,
                "cover_letter_enabled": True,
                "cover_letter_pages": 1,
            },
        }

        self.assertEqual(validate_document("config", valid), [])

    def test_json_constants_and_enums_do_not_treat_booleans_as_numbers(self) -> None:
        const_errors = validate_document(
            "next-job-id", {"schema_version": True, "next_id": 1}
        )
        self.assertIn("invalid_const", {error.code for error in const_errors})

        config = {
            "schema_version": 2,
            "workspace_root": "/approved-at-runtime",
            "timezone": "America/New_York",
            "paths": {
                "profile": "Profile",
                "sources": "Sources",
                "jobs": "Jobs",
                "applications": "Applications",
                "indexes": "Indexes",
                "runs": "Runs",
                "state": "State",
            },
            "profile_approved": True,
            "criteria_approved": True,
            "connectors": {},
            "enabled_sources": ["public_ats"],
            "discovery_schedule": {
                "frequency": "weekday",
                "weekdays": ["MO"],
                "runs_per_day": 1,
                "timezone": "America/New_York",
            },
            "packet_defaults": {
                "resume_pages": 2,
                "cover_letter_enabled": False,
                "cover_letter_pages": True,
            },
        }
        enum_errors = validate_document("config", config)
        self.assertIn("invalid_enum", {error.code for error in enum_errors})

    def test_schema_patterns_follow_json_schema_search_semantics(self) -> None:
        manifest = {
            "schema_version": 1,
            "packets": {
                "JOB-000001": [
                    {
                        "job_id": "JOB-000001",
                        "employer": "Example",
                        "title": "Operator",
                        "version": "v001",
                        "version_dir": "Applications/JOB-000001_Example/v001",
                        "resume_pdf": "Applications/JOB-000001_Example/v001/Resume.pdf",
                        "cover_letter_pdf": None,
                        "working_dir": "Applications/JOB-000001_Example/v001/working",
                        "stage": "selected",
                        "receipts": {},
                        "profile_hash": None,
                    }
                ]
            },
        }

        self.assertEqual(validate_document("application-manifest", manifest), [])

    def test_traversal_and_unknown_schema_version_are_rejected(self) -> None:
        invalid = {
            "schema_version": 9,
            "workspace_root": "/approved-at-runtime",
            "timezone": "America/New_York",
            "paths": {
                "profile": "../Profile",
                "sources": "Sources",
                "jobs": "Jobs",
                "applications": "Applications",
                "indexes": "Indexes",
                "runs": "Runs",
                "state": "State",
            },
            "profile_approved": False,
            "criteria_approved": False,
            "connectors": {},
            "enabled_sources": ["public_ats"],
            "discovery_schedule": {
                "frequency": "weekday",
                "weekdays": ["MO"],
                "runs_per_day": 1,
                "timezone": "America/New_York",
            },
            "packet_defaults": {
                "resume_pages": 2,
                "cover_letter_enabled": False,
                "cover_letter_pages": 0,
            },
        }

        codes = {error.code for error in validate_document("config", invalid)}
        self.assertEqual(codes, {"schema_version", "relative_path"})


if __name__ == "__main__":
    unittest.main()
