from __future__ import annotations

import unittest

from career_pipeline.dedupe import (
    fallback_fingerprint,
    partition_candidates,
    requisition_key,
)
from career_pipeline.sources.base import CandidateJob
from career_pipeline.sources.generic import normalize
from career_pipeline.sources.base import SourceSnapshot


def job(source: str, requisition: str | None, team: str | None = "Operations") -> CandidateJob:
    return normalize(
        SourceSnapshot(
            source,
            "2026-09-11T12:00:00Z",
            [
                {
                    "source_record_id": f"{source}-record",
                    "requisition_id": requisition,
                    "employer": "Example Organization",
                    "title": "Operations Lead",
                    "responsibilities": ["Build an operating cadence."],
                    "location": "New York, NY",
                    "team": team,
                    "posting_url": f"https://jobs.example/{source}/posting",
                    "application_url": f"https://jobs.example/{source}/apply"
                }
            ],
        )
    )[0]


class DedupeTests(unittest.TestCase):
    def test_same_requisition_across_sources_is_duplicate(self) -> None:
        ats = job("greenhouse", "SYN-204")
        broad = job("public-search", "syn-204")
        self.assertEqual(requisition_key(ats), requisition_key(broad))
        partition = partition_candidates([broad], [ats])
        self.assertEqual(partition.novel, ())
        self.assertEqual(partition.duplicates, (broad,))

    def test_fallback_keeps_different_teams_distinct(self) -> None:
        first = job("public-search", None, "Operations")
        second = job("browser", None, "Product")
        self.assertNotEqual(fallback_fingerprint(first), fallback_fingerprint(second))


if __name__ == "__main__":
    unittest.main()
