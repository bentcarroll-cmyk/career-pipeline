"""Whole-board capture cannot claim support for unimplemented geography filters."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from career_pipeline import retrieval, review_queue
from career_pipeline.atomic import atomic_write_json
from career_pipeline.workspace import create_workspace


NOW = "2026-09-15T12:00:00Z"


class RetrievalScopeQueryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = create_workspace(Path(temp.name))

    def test_board_registration_rejects_unimplemented_location_filter_without_writes(self):
        for provider in ("greenhouse", "ashby", "lever"):
            with self.subTest(provider=provider), self.assertRaisesRegex(ValueError, "unsupported_board_query_fields"):
                retrieval.register_scope(
                    self.workspace, run_id="filtered-board", source=provider, provider=provider,
                    query={"board": "example", "employer": "Example", "location": "US"}, now=NOW,
                )
        self.assertEqual(retrieval.load_ledger(self.workspace)["scopes"], {})

    def test_legacy_filtered_scope_cannot_accept_manual_capture_as_complete(self):
        scope = retrieval.register_scope(
            self.workspace, run_id="filtered-board", source="greenhouse", provider="greenhouse",
            query={"board": "example", "employer": "Example"}, now=NOW,
        )
        ledger = retrieval.load_ledger(self.workspace)
        del ledger["scopes"][scope["scope_id"]]
        scope = copy.deepcopy(scope)
        scope["query"]["location"] = "US"
        identity = {key: scope[key] for key in ("run_id", "source", "provider", "query")}
        scope["scope_id"] = "scope:" + review_queue._digest(identity)
        ledger["scopes"][scope["scope_id"]] = scope
        atomic_write_json(self.workspace.state / "discovery-retrieval.json", ledger)
        response = {"jobs": [], "meta": {"total": 0}}
        try:
            captured = retrieval.capture_response(self.workspace, scope["scope_id"], response, now=NOW)
        except ValueError:
            captured = retrieval.load_ledger(self.workspace)["scopes"][scope["scope_id"]]
        self.assertNotEqual(captured.get("complete"), True)
        saved = retrieval.load_ledger(self.workspace)["scopes"][scope["scope_id"]]
        self.assertEqual(len(saved["pages"]), 1)
        self.assertEqual(json.loads((self.workspace.root / saved["pages"][0]["snapshot"]).read_text()), response)
        report = retrieval.summary(self.workspace, now=NOW)
        self.assertFalse(report["complete"])
        self.assertTrue(any(p["reason"] == "retrieval_evidence_invalid" for p in report["pending"]))
        self.assertEqual(review_queue.load_queue(self.workspace)["items"], {})
