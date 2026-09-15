"""Acceptance checks across real acquisition, intake, review and checkpoints."""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

from career_pipeline import review_queue
from career_pipeline.checkpoints import DiscoveryState, SourceResult, merge_discovery_state
from career_pipeline.workspace import create_workspace


NOW = "2026-09-15T12:00:00+00:00"
LATER = "2026-09-15T12:01:00+00:00"


def posting(identifier):
    return {
        "id": identifier,
        "text": "Specialist Operations",
        "categories": {"location": "Remote US", "team": "Operations"},
        "descriptionPlain": "Requires a specialist credential absent from the test profile.",
        "lists": [{"text": "Responsibilities", "content": "Lead specialist operations."}],
        "additionalPlain": "Full time.",
        "hostedUrl": f"https://jobs.lever.co/example/{identifier}",
        "applyUrl": f"https://jobs.lever.co/example/{identifier}/apply",
        "workplaceType": "remote",
    }


class RetrievalFlowTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("career_pipeline.retrieval"),
                             "Retrieval evidence must gate source completion")
        self.retrieval = importlib.import_module("career_pipeline.retrieval")
        self.collectors = importlib.import_module("career_pipeline.collectors")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = create_workspace(Path(self.temp.name))

    def scope(self, run_id="test-run"):
        return self.retrieval.register_scope(
            self.workspace, run_id=run_id, source="lever", provider="lever",
            query={"board": "example", "employer": "Example Cooperative", "page_size": 2},
            now=NOW,
        )

    def review_all(self):
        for item in review_queue.next_items(self.workspace, now=LATER):
            review_queue.record_decision(
                self.workspace, item["review_id"],
                {"status": "non_match",
                 "rationale": "The required specialist credential is absent from the synthetic profile.",
                 "evidence": [item["posting_url"]]},
                expected_revision=item["revision"], expected_context=item["expected_context"],
                now=LATER,
            )

    def result(self, scope):
        return SourceResult(
            success=True, completed_at=LATER,
            seen_records=tuple(scope["source_record_ids"]), cursor=None,
            intake_ids=tuple(scope["intake_ids"]),
            coverage_scope_ids=(scope["scope_id"],),
        )

    def test_complete_paginated_board_is_reviewed_before_checkpoint_advances(self):
        scope = self.scope()
        pages = {
            "https://api.lever.co/v0/postings/example?mode=json&skip=0&limit=2": [posting("one"), posting("two")],
            "https://api.lever.co/v0/postings/example?mode=json&skip=2&limit=2": [posting("three")],
        }
        fetched = []

        def fetch(url):
            fetched.append(url)
            # Permit query parameter order variation, but no filters or different values.
            from urllib.parse import parse_qs, urlsplit
            request = urlsplit(url)
            self.assertEqual(request.netloc, "api.lever.co")
            self.assertEqual(request.path, "/v0/postings/example")
            query = parse_qs(request.query)
            self.assertEqual(set(query), {"mode", "skip", "limit"})
            self.assertEqual(query["mode"], ["json"])
            self.assertEqual(query["limit"], ["2"])
            canonical = f"https://api.lever.co/v0/postings/example?mode=json&skip={query['skip'][0]}&limit=2"
            return pages[canonical]

        for cursor in (None, "2"):
            response = self.collectors.fetch_board_page(
                "lever", query=scope["query"], cursor=cursor, fetch_json=fetch,
            )
            scope = self.retrieval.capture_response(
                self.workspace, scope["scope_id"], response, now=NOW, cursor=cursor,
            )
        self.assertEqual(len(fetched), 2)
        self.assertEqual(review_queue.summary(self.workspace, now=NOW)["unreviewed"], 3)
        self.assertFalse(review_queue.summary(self.workspace, now=NOW)["complete"])
        with self.assertRaises(ValueError):
            merge_discovery_state(self.workspace, DiscoveryState(), (("lever", self.result(scope)),))
        self.assertFalse((self.workspace.state / "discovery-state.json").exists())
        self.review_all()
        state = merge_discovery_state(self.workspace, DiscoveryState(), (("lever", self.result(scope)),))
        self.assertEqual(set(state.sources["lever"].seen_records), {"one", "two", "three"})
        self.assertTrue(review_queue.summary(self.workspace, now=LATER)["complete"])

    def test_reviewing_full_first_page_does_not_advance_or_lose_continuation(self):
        scope = self.scope()
        scope = self.retrieval.capture_response(
            self.workspace, scope["scope_id"], [posting("one"), posting("two")], now=NOW,
        )
        self.review_all()
        self.assertEqual(scope["next_cursor"], "2")
        self.assertTrue(review_queue.summary(self.workspace, now=LATER)["review_complete"])
        self.assertFalse(review_queue.summary(self.workspace, now=LATER)["complete"])
        with self.assertRaisesRegex(ValueError, "retrieval"):
            merge_discovery_state(self.workspace, DiscoveryState(), (("lever", self.result(scope)),))
        self.assertFalse((self.workspace.state / "discovery-state.json").exists())

    def test_registered_ninth_query_cannot_be_omitted_from_completion(self):
        scopes = [self.retrieval.register_scope(
            self.workspace, run_id="nine-board-run", source="ashby", provider="ashby",
            query={"board": f"example-{number}", "employer": "Example Cooperative"}, now=NOW,
        ) for number in range(9)]
        complete = [self.retrieval.capture_response(
            self.workspace, scope["scope_id"], {"jobs": []}, now=NOW,
        ) for scope in scopes[:8]]
        result = SourceResult(
            True, LATER, (), None,
            tuple({batch for scope in complete for batch in scope["intake_ids"]}),
            tuple(scope["scope_id"] for scope in complete),
        )
        with self.assertRaisesRegex(ValueError, "retrieval"):
            merge_discovery_state(self.workspace, DiscoveryState(), (("ashby", result),))
        self.assertFalse(review_queue.summary(self.workspace, now=LATER)["complete"])
        self.assertFalse((self.workspace.state / "discovery-state.json").exists())


if __name__ == "__main__":
    unittest.main()
