import unittest

from career_pipeline.schema import validate_document


def valid_job() -> dict[str, object]:
    return {
        "schema_version": 1,
        "job_id": "JOB-000123",
        "source_record_id": "synthetic-record-123",
        "employer": "Example Cooperative",
        "title": "Director of Operations",
        "location": "Example City",
        "workplace_model": "hybrid",
        "travel": None,
        "compensation_evidence": None,
        "posting_url": "https://jobs.example/postings/SYN-123",
        "application_url": "https://jobs.example/apply/SYN-123",
        "requisition_id": "SYN-123",
        "source": "greenhouse",
        "verified_at": "2026-09-11T12:00:00Z",
        "verification_status": "verified",
        "raw_field_hash": "a" * 64,
        "disposition": "strong_match",
        "status": "new",
        "role_to_profile_fit": "Synthetic evidence supports the core work.",
        "strengths": [],
        "gaps": [],
        "uncertainties": [],
        "deadline": None,
        "recommended_next_action": "Review the role.",
        "discovered_at": "2026-09-11T12:00:00Z",
        "reverified_at": None,
        "paths": {
            "posting": "Jobs/JOB-000123/posting.md",
            "assessment": "Jobs/JOB-000123/assessment.md",
            "events": "Jobs/JOB-000123/events.jsonl",
            "working": "Jobs/JOB-000123/working",
        },
        "application_versions": [],
        "exports": [],
    }


class JobContractTests(unittest.TestCase):
    def test_minimal_canonical_job_is_valid(self) -> None:
        self.assertEqual(validate_document("job", valid_job()), [])

    def test_id_status_and_relative_paths_are_validated(self) -> None:
        invalid = valid_job()
        invalid["job_id"] = "SYN-123"
        invalid["status"] = "deleted"
        invalid["paths"] = {
            **invalid["paths"],
            "working": "/tmp/private-working",
        }

        codes = {error.code for error in validate_document("job", invalid)}
        self.assertEqual(codes, {"job_id", "job_status", "relative_path"})

    def test_job_folder_paths_must_match_the_local_id(self) -> None:
        invalid = valid_job()
        invalid["paths"] = {
            **invalid["paths"],
            "posting": "Jobs/JOB-000999/posting.md",
        }

        errors = validate_document("job", invalid)
        self.assertEqual([error.code for error in errors], ["job_path_mismatch"])


if __name__ == "__main__":
    unittest.main()
