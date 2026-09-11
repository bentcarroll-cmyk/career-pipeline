import unittest

from career_pipeline.schema import validate_document


class SchemaTests(unittest.TestCase):
    def test_config_requires_timezone_and_relative_subpaths(self) -> None:
        valid = {
            "schema_version": 1,
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
            "packet_defaults": {
                "resume_pages": 2,
                "cover_letter_enabled": True,
                "cover_letter_pages": 1,
            },
        }
        self.assertEqual(validate_document("config", valid), [])

        invalid = {**valid, "timezone": "", "paths": {**valid["paths"], "state": "/fixed"}}
        codes = {error.code for error in validate_document("config", invalid)}
        self.assertEqual(codes, {"required_string", "relative_path"})

    def test_linear_is_optional_configuration(self) -> None:
        valid = {
            "schema_version": 1,
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
            "packet_defaults": {
                "resume_pages": 2,
                "cover_letter_enabled": True,
                "cover_letter_pages": 1,
            },
        }

        self.assertEqual(validate_document("config", valid), [])

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
