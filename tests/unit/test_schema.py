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
                "applications": "Applications",
                "runs": "Runs",
                "state": "State",
            },
            "linear": {"workspace_id": "synthetic", "team_id": "synthetic"},
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


if __name__ == "__main__":
    unittest.main()
