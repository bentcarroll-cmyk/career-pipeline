import json
import unittest
from pathlib import Path

from career_pipeline.dedupe import partition_candidates
from career_pipeline.sources.base import SourceSnapshot
from career_pipeline.sources.greenhouse import normalize as normalize_greenhouse
from career_pipeline.sources.generic import normalize as normalize_generic


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic" / "postings"


class CrossSourceDiscoveryTests(unittest.TestCase):
    def test_archived_baseline_still_blocks_duplicate_requisition(self) -> None:
        greenhouse = json.loads((FIXTURES / "greenhouse.json").read_text(encoding="utf-8"))
        existing_archived = normalize_greenhouse(
            SourceSnapshot("greenhouse", "2026-09-11T12:00:00Z", greenhouse)
        )[0]
        broad = [
            {
                "source_record_id": "broad-copy",
                "requisition_id": "SYN-GH-101",
                "employer": "Northstar Example Cooperative",
                "title": "Director of Operations",
                "responsibilities": ["Lead planning and operations."],
                "location": "New York, NY",
                "posting_url": "https://jobs.example/postings/SYN-GH-101",
                "application_url": "https://jobs.example/apply/SYN-GH-101"
            }
        ]
        discovered = normalize_generic(
            SourceSnapshot("public-search", "2026-09-11T13:00:00Z", broad)
        )[0]
        result = partition_candidates([discovered], [existing_archived])
        self.assertEqual(result.novel, ())
        self.assertEqual(result.duplicates, (discovered,))


if __name__ == "__main__":
    unittest.main()
