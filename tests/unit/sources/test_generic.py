import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from career_pipeline.sources.base import SourceSnapshot
from career_pipeline.sources.generic import normalize


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic" / "postings"


class GenericAdapterTests(unittest.TestCase):
    def test_preserves_generic_source_attribution_and_raw_hash(self) -> None:
        payload = json.loads((FIXTURES / "generic.json").read_text(encoding="utf-8"))
        job = normalize(SourceSnapshot("public-search", "2026-09-11T12:00:00Z", payload))[0]

        self.assertEqual(job.source, "public-search")
        self.assertEqual(len(job.raw_field_hash), 64)
        self.assertEqual(job.workplace_model, "hybrid")
        self.assertEqual(job.verified_at, "2026-09-11T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
