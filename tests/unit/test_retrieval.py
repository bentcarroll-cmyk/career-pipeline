import importlib.util
import copy
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from career_pipeline import review_queue as q
from career_pipeline.checkpoints import DiscoveryState, SourceResult, merge_discovery_state
from career_pipeline.workspace import create_workspace

NOW = "2026-09-15T12:00:00Z"
LATER = "2026-09-15T13:00:00Z"


def gh_job(number=1, description="Lead operations and customer workflows."):
    return {"id": number, "title": f"Operations Lead {number}",
            "absolute_url": f"https://example.test/jobs/{number}",
            "location": {"name": "Remote US"}, "content": description}


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("career_pipeline.retrieval"),
                             "Durable retrieval accounting is required before source completion")
        from career_pipeline import retrieval
        self.r = retrieval
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = create_workspace(Path(self.temp.name))

    def scope(self, provider="greenhouse", source=None, query=None, run="run-1"):
        return self.r.register_scope(self.ws, run_id=run, source=source or provider,
                                     provider=provider, query=query or {"board": "example", "employer": "Example"}, now=NOW)

    def capture(self, scope, jobs=None):
        return self.r.capture_response(self.ws, scope["scope_id"],
            {"jobs": [gh_job()] if jobs is None else jobs, "meta": {"total": 1 if jobs is None else len(jobs)}}, now=NOW)

    def decide_all(self):
        for row in q.load_queue(self.ws)["items"].values():
            q.record_decision(self.ws, row["review_id"], {"status": "non_match",
                "rationale": "The documented requirements do not match the approved profile.",
                "evidence": [row["posting_url"]]}, expected_revision=row["revision"],
                expected_context=q.review_context(self.ws), now=NOW)

    def result(self, scope):
        return {"success": True, "completed_at": LATER, "cursor": None,
                "coverage_scope_ids": [scope["scope_id"]], "intake_ids": scope["intake_ids"],
                "seen_records": scope["source_record_ids"]}

    def test_legacy_review_complete_is_unknown_retrieval(self):
        self.assertTrue(q.summary(self.ws, now=NOW)["review_complete"])
        self.assertFalse(q.summary(self.ws, now=NOW)["complete"])
        self.assertEqual(self.r.summary(self.ws, now=NOW)["status"], "unknown")
        with self.assertRaisesRegex(ValueError, "retrieval"):
            merge_discovery_state(self.ws, DiscoveryState(), (("greenhouse", SourceResult(True, NOW, (), None)),))
        self.assertFalse((self.ws.state / "discovery-state.json").exists())

    def test_reviewed_ten_of_840_cannot_complete(self):
        scope = self.scope("indeed", query={"query": "operations"})
        response = {"jobs": [{"jrtk": str(i), "title": f"Operations {i}", "company": "Example",
            "url": f"https://example.test/jobs/{i}", "description": "Lead operations.", "location": "Remote US"}
            for i in range(10)], "totalAvailable": 840, "truncated": True}
        scope = self.r.capture_response(self.ws, scope["scope_id"], response, now=NOW)
        self.decide_all()
        result = q.summary(self.ws, now=NOW)
        self.assertEqual(result["total"], 10)
        self.assertTrue(result["review_complete"])
        self.assertFalse(result["complete"])
        with self.assertRaisesRegex(ValueError, "retrieval"):
            q.validate_delivery(self.ws, {"source_results": {"indeed": self.result(scope)}}, now=LATER)

    def test_ninth_registered_scope_cannot_be_omitted(self):
        scopes = [self.scope(query={"board": f"example{i}", "employer": "Example"}) for i in range(9)]
        for scope in scopes[:8]:
            self.capture(scope, [])
        report = self.r.summary(self.ws, now=NOW)
        self.assertFalse(report["complete"])
        self.assertTrue(any(p["scope_id"] == scopes[8]["scope_id"] for p in report["pending"]))
        first = self.r.load_ledger(self.ws)["scopes"][scopes[0]["scope_id"]]
        with self.assertRaisesRegex(ValueError, "retrieval"):
            self.r.validate_source_result(self.ws, "greenhouse", self.result(first), now=LATER)

    def test_missing_description_pointer_can_only_resolve_with_matching_full_record(self):
        scope = self.capture(self.scope(), [gh_job(description="")])
        self.assertEqual(len(scope["unresolved_pointers"]), 1)
        self.assertEqual(len(q.load_queue(self.ws)["items"]), 0)
        record = {"source": "greenhouse", "source_record_id": "1", "employer": "Example",
            "title": "Operations Lead 1", "posting_url": "https://example.test/jobs/1",
            "raw": {"description": "Full employer posting now retrieved."}}
        with self.assertRaises(ValueError):
            self.r.resolve_pointer(self.ws, scope["scope_id"], source_record_id="1", record={**record, "source_record_id": "2"}, now=NOW)
        scope = self.r.resolve_pointer(self.ws, scope["scope_id"], source_record_id="1", record=record, now=NOW)
        self.assertEqual(scope["unresolved_pointers"], [])
        self.assertTrue(self.r.summary(self.ws, now=NOW)["complete"])
        repeated = self.r.resolve_pointer(self.ws, scope["scope_id"], source_record_id="1", record=record, now=LATER)
        self.assertEqual(repeated["intake_ids"], scope["intake_ids"])

    def test_capture_survives_interrupted_ingestion_and_replay_is_idempotent(self):
        scope = self.scope()
        with patch.object(q, "ingest", side_effect=RuntimeError("interrupted ingestion")):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                self.capture(scope)
        saved = self.r.load_ledger(self.ws)["scopes"][scope["scope_id"]]
        self.assertEqual(len(saved["pages"]), 1)
        self.assertTrue((self.ws.root / saved["pages"][0]["snapshot"]).is_file())
        self.assertFalse(self.r.summary(self.ws, now=NOW)["complete"])
        scope = self.capture(scope)
        self.capture(scope)
        queue = q.load_queue(self.ws)
        self.assertEqual(len(queue["items"]), 1)
        self.assertEqual(len(queue["intake_batches"]), 1)
        self.assertEqual(len(next(iter(queue["items"].values()))["observations"]), 1)
        self.assertTrue(self.r.summary(self.ws, now=NOW)["complete"])

    def test_empty_board_can_complete_but_unattempted_cannot(self):
        scope = self.scope()
        self.assertFalse(self.r.summary(self.ws, now=NOW)["complete"])
        scope = self.capture(scope, [])
        q.validate_delivery(self.ws, {"source_results": {"greenhouse": self.result(scope)}}, now=LATER)
        self.assertTrue(q.summary(self.ws, now=NOW)["complete"])

    def test_tampered_raw_or_intake_receipts_cannot_complete(self):
        scope = self.capture(self.scope())
        self.decide_all()
        result = self.result(scope)
        q.validate_delivery(self.ws, {"source_results": {"greenhouse": result}}, now=LATER)
        path = self.ws.root / scope["pages"][0]["snapshot"]
        original = path.read_text()
        path.write_text("{}")
        with self.assertRaisesRegex(ValueError, "retrieval"):
            self.r.validate_source_result(self.ws, "greenhouse", result, now=LATER)
        path.write_text(original)
        queue = q.load_queue(self.ws)
        queue["intake_batches"][result["intake_ids"][0]]["source_record_ids"] = []
        (self.ws.state / "discovery-review-queue.json").write_text(json.dumps(queue))
        with self.assertRaisesRegex(ValueError, "retrieval"):
            self.r.validate_source_result(self.ws, "greenhouse", result, now=LATER)

    def test_malformed_response_is_retained_and_retry_can_complete(self):
        scope = self.scope()
        bad = self.r.capture_response(self.ws, scope["scope_id"], {"meta": {"total": 1}}, now=NOW)
        self.assertEqual(len(bad["pages"]), 1)
        self.assertFalse(self.r.summary(self.ws, now=NOW)["complete"])
        self.capture(scope)
        self.assertTrue(self.r.summary(self.ws, now=NOW)["complete"])

    def test_foreign_stale_omitted_or_future_scope_cannot_checkpoint(self):
        scope = self.capture(self.scope())
        result = self.result(scope)
        for change in ({"coverage_scope_ids": []}, {"coverage_scope_ids": ["foreign"]},
                       {"intake_ids": []}, {"seen_records": []}, {"completed_at": "2026-09-14T12:00:00Z"}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "retrieval"):
                self.r.validate_source_result(self.ws, "greenhouse", {**result, **change}, now=LATER)
        self.scope(run="newer-run")
        with self.assertRaisesRegex(ValueError, "retrieval"):
            self.r.validate_source_result(self.ws, "greenhouse", result, now=LATER)

    def test_later_completed_run_requires_only_its_receipts_even_at_same_timestamp(self):
        older = self.capture(self.scope(run="older-z"))
        newer = self.capture(self.scope(run="newer-a"), [])
        self.r.validate_source_result(self.ws, "greenhouse", self.result(newer), now=LATER)
        with self.assertRaisesRegex(ValueError, "retrieval"):
            self.r.validate_source_result(self.ws, "greenhouse", self.result(older), now=LATER)

    def test_invalid_extra_response_after_completed_page_stays_incomplete(self):
        scope = self.capture(self.scope())
        scope = self.r.capture_response(self.ws, scope["scope_id"], {"unexpected": "response"}, now=NOW)
        self.assertFalse(scope["complete"])
        self.assertFalse(self.r.summary(self.ws, now=NOW)["complete"])
        with self.assertRaisesRegex(ValueError, "retrieval"):
            self.r.validate_source_result(self.ws, "greenhouse", self.result(scope), now=LATER)

    def test_pointer_resolution_cannot_substitute_a_known_employer_or_url(self):
        scope = self.capture(self.scope(), [gh_job(description="")])
        record = {"source": "greenhouse", "source_record_id": "1", "employer": "Example",
            "title": "Operations Lead 1", "posting_url": "https://example.test/jobs/1",
            "raw": {"description": "Full posting content."}}
        for change in ({"employer": "Unrelated Corp"}, {"posting_url": "https://other.test/job"}, {"title": "Different job"}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "identity"):
                self.r.resolve_pointer(self.ws, scope["scope_id"], source_record_id="1", record={**record, **change}, now=NOW)

    def test_replay_scope_repairs_saved_response_without_new_provider_data(self):
        scope = self.scope()
        with patch.object(q, "ingest", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                self.capture(scope)
        self.assertTrue(hasattr(self.r, "replay_scope"), "Saved captures need a public resume path")
        scope = self.r.replay_scope(self.ws, scope["scope_id"], now=LATER)
        self.assertTrue(scope["complete"])
        self.assertEqual(len(q.load_queue(self.ws)["items"]), 1)

    def test_unlisted_ashby_rows_are_accounted_without_publication_intake(self):
        scope = self.scope("ashby")
        scope = self.r.capture_response(self.ws, scope["scope_id"], {"jobs": [{"id": "unlisted",
            "title": "Private opening", "jobUrl": "https://jobs.ashbyhq.com/example/unlisted",
            "descriptionPlain": "Not available for public application.", "isListed": False}]}, now=NOW)
        self.assertEqual(scope["returned_records"], 1)
        self.assertEqual(scope["ingested_records"], 0)
        self.assertEqual(scope["non_public_dispositions"], [{"source_record_id": "unlisted", "reason": "provider_unlisted"}])
        self.assertTrue(scope["complete"])
        self.assertEqual(q.load_queue(self.ws)["items"], {})
        self.r.validate_source_result(self.ws, "ashby", self.result(scope), now=LATER)

    def test_failed_continuation_and_wrong_cursor_do_not_erase_pending_work(self):
        scope = self.scope("lever", query={"board": "example", "employer": "Example", "page_size": 1})
        first = [{"id": "1", "text": "Operations", "hostedUrl": "https://example.test/jobs/1", "descriptionPlain": "Lead operations."}]
        scope = self.r.capture_response(self.ws, scope["scope_id"], first, now=NOW)
        self.assertEqual(scope["next_cursor"], "1")
        self.r.record_failure(self.ws, scope["scope_id"], now=NOW, reason="network_error", next_action="Retry cursor 1.")
        scope = self.r.capture_response(self.ws, scope["scope_id"], [], cursor="99", now=NOW)
        self.assertEqual(scope["next_cursor"], "1")
        scope = self.r.capture_response(self.ws, scope["scope_id"], [], cursor="1", now=NOW)
        self.assertFalse(scope["complete"], "Unexpected cursor capture cannot be erased by a different valid page")

    def test_enabled_source_without_registered_scope_keeps_discovery_incomplete(self):
        (self.ws.state / "config.json").write_text(json.dumps({"enabled_sources": ["public_ats", "indeed"]}))
        scope = self.capture(self.scope(), [])
        report = self.r.summary(self.ws, now=NOW)
        self.assertFalse(report["complete"])
        self.assertEqual(report["missing_enabled_sources"], ["indeed"])
        self.assertFalse(q.summary(self.ws, now=NOW)["complete"])
        # A completed independent source may advance while global discovery is partial.
        self.r.validate_source_result(self.ws, "public_ats", self.result(scope), now=LATER)

    def test_old_run_scope_does_not_cover_an_enabled_lane_missing_from_new_run(self):
        (self.ws.state / "config.json").write_text(json.dumps({"enabled_sources": ["greenhouse", "ashby"]}))
        old = self.scope("ashby", run="old")
        self.r.capture_response(self.ws, old["scope_id"], {"jobs": []}, now=NOW)
        self.capture(self.scope(run="new"), [])
        report = self.r.summary(self.ws, now=NOW)
        self.assertFalse(report["complete"])
        self.assertEqual(report["missing_enabled_sources"], ["ashby"])

    def test_network_failure_retries_exact_next_cursor_and_completes(self):
        scope = self.scope("lever", query={"board": "example", "employer": "Example", "page_size": 1})
        first = [{"id": "1", "text": "Operations", "hostedUrl": "https://example.test/jobs/1", "descriptionPlain": "Lead operations."}]
        scope = self.r.capture_response(self.ws, scope["scope_id"], first, now=NOW)
        failed = self.r.record_failure(self.ws, scope["scope_id"], now=NOW, reason="network_error", next_action="Retry cursor 1.")
        self.assertEqual(failed["next_cursor"], "1")
        scope = self.r.capture_response(self.ws, scope["scope_id"], [], cursor="1", now=NOW)
        self.assertTrue(scope["complete"])
        self.assertEqual(len(scope["failures"]), 1)
        self.assertEqual(len(scope["pages"]), 2)

    def test_pointer_ingestion_interruption_replays_original_resolution(self):
        scope = self.capture(self.scope(), [gh_job(description="")])
        record = {"source": "greenhouse", "source_record_id": "1", "employer": "Example",
            "title": "Operations Lead 1", "posting_url": "https://example.test/jobs/1",
            "raw": {"description": "Recovered full official description."}}
        with patch.object(q, "ingest", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                self.r.resolve_pointer(self.ws, scope["scope_id"], source_record_id="1", record=record, now=NOW)
        scope = self.r.replay_scope(self.ws, scope["scope_id"], now=LATER)
        self.assertTrue(scope["complete"])
        self.assertEqual(scope["source_record_ids"], ["1"])

    def test_old_page_and_pointer_recovery_preserve_newer_review_and_delivery(self):
        after = "2026-09-15T14:00:00Z"
        for kind in ("page", "pointer"):
            for newer_at in (NOW, LATER):
                for intake_committed in (False, True):
                    with self.subTest(kind=kind, newer_at=newer_at, intake_committed=intake_committed), tempfile.TemporaryDirectory() as folder:
                        ws = create_workspace(Path(folder))
                        old = self.r.register_scope(ws, run_id="older", source="greenhouse", provider="greenhouse",
                            query={"board": "example", "employer": "Example"}, now=NOW)
                        if kind == "pointer":
                            self.r.capture_response(ws, old["scope_id"], {"jobs": [gh_job(description="")]}, now=NOW)
                        ingest = q.ingest

                        def interrupt(*args, **kwargs):
                            if intake_committed:
                                ingest(*args, **kwargs)
                            raise OSError("interrupted intake")

                        with patch.object(q, "ingest", side_effect=interrupt), self.assertRaisesRegex(OSError, "interrupted intake"):
                            if kind == "page":
                                self.r.capture_response(ws, old["scope_id"], {"jobs": [gh_job(description="OLD office-only duties.")]}, now=NOW)
                            else:
                                self.r.resolve_pointer(ws, old["scope_id"], source_record_id="1", now=NOW,
                                    record={"source": "greenhouse", "source_record_id": "1", "employer": "Example",
                                            "title": "Operations Lead 1", "posting_url": "https://example.test/jobs/1",
                                            "raw": {"description": "OLD office-only duties."}})
                        newer = self.r.register_scope(ws, run_id="newer", source="greenhouse", provider="greenhouse",
                            query={"board": "example", "employer": "Example"}, now=newer_at)
                        newer = self.r.capture_response(ws, newer["scope_id"],
                            {"jobs": [gh_job(description="NEW fully remote duties.")]}, now=newer_at)
                        current = q.next_items(ws, now=newer_at)[0]
                        q.record_decision(ws, current["review_id"], {"status": "qualifying",
                            "rationale": "The current responsibilities fit the approved evidence.", "evidence": [current["posting_url"]]},
                            expected_revision=current["revision"], expected_context=current["expected_context"], now=newer_at)
                        q.mark_delivered(ws, current, "JOB-000001")
                        before = copy.deepcopy(q.load_queue(ws)["items"][current["review_id"]])
                        evidence = {path: path.read_bytes() for path in (ws.sources / "discovery-retrieval").glob("*.json")}

                        recovered = self.r.replay_scope(ws, old["scope_id"], now=after)
                        actual = q.load_queue(ws)["items"][current["review_id"]]
                        for field in ("content_hash", "active_snapshot_hash", "decision", "job_id", "revision", "history", "last_seen_at"):
                            self.assertEqual(actual[field], before[field], field)
                        if newer_at == NOW:
                            self.assertFalse(recovered["complete"])
                            self.assertTrue(any(p["reason"] == "capture_time_conflict" for p in recovered["pending"]))
                            with self.assertRaisesRegex(ValueError, "review_queue_incomplete"):
                                q.validate_delivery(ws, {"source_results": {"greenhouse": {
                                    "success": True, "completed_at": after, "coverage_scope_ids": [newer["scope_id"]],
                                    "seen_records": newer["source_record_ids"], "intake_ids": newer["intake_ids"]}}},
                                    now=after, require_delivered=True)
                            self.r.replay_scope(ws, old["scope_id"], now=after)
                            self.assertEqual(q.load_queue(ws)["items"][current["review_id"]], actual)
                            refreshed = self.r.register_scope(ws, run_id="fresh-after-conflict", source="greenhouse", provider="greenhouse",
                                query={"board": "example", "employer": "Example"}, now=after)
                            newer = self.r.capture_response(ws, refreshed["scope_id"],
                                {"jobs": [gh_job(description="NEW fully remote duties.")]}, now=after)
                            current = q.next_items(ws, now=after)[0]
                            q.record_decision(ws, current["review_id"], before["decision"], expected_revision=current["revision"],
                                expected_context=current["expected_context"], now=after)
                            q.mark_delivered(ws, current, "JOB-000001")
                            actual = q.load_queue(ws)["items"][current["review_id"]]
                        else:
                            self.assertTrue(recovered["complete"])
                        self.assertEqual(recovered["source_record_ids"], ["1"])
                        self.assertTrue(recovered["intake_ids"])
                        q.validate_delivery(ws, {"source_results": {"greenhouse": {
                            "success": True, "completed_at": after, "coverage_scope_ids": [newer["scope_id"]],
                            "seen_records": newer["source_record_ids"], "intake_ids": newer["intake_ids"]}}},
                            now=after, require_delivered=True)
                        for path, original in evidence.items():
                            self.assertEqual(path.read_bytes(), original)
                        self.r.replay_scope(ws, old["scope_id"], now=after)
                        self.assertEqual(q.load_queue(ws)["items"][current["review_id"]], actual)

    def test_interrupted_newer_equal_time_capture_needs_fresh_evidence_before_completion(self):
        for kind in ("page", "pointer"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                ws = create_workspace(Path(folder))
                older = self.r.register_scope(ws, run_id="older", source="greenhouse", provider="greenhouse",
                    query={"board": "example", "employer": "Example"}, now=NOW)
                self.r.capture_response(ws, older["scope_id"], {"jobs": [gh_job(description="OLD specialist duties.")]}, now=NOW)
                row = q.next_items(ws, now=NOW)[0]
                q.record_decision(ws, row["review_id"], {"status": "non_match",
                    "rationale": "The original specialist duties do not fit the approved profile.", "evidence": [row["posting_url"]]},
                    expected_revision=row["revision"], expected_context=row["expected_context"], now=NOW)
                before = copy.deepcopy(q.load_queue(ws)["items"][row["review_id"]])
                newer = self.r.register_scope(ws, run_id="newer", source="greenhouse", provider="greenhouse",
                    query={"board": "example", "employer": "Example"}, now=NOW)
                if kind == "pointer":
                    self.r.capture_response(ws, newer["scope_id"], {"jobs": [gh_job(description="")]}, now=NOW)
                with patch.object(q, "ingest", side_effect=OSError("interrupted new intake")), self.assertRaises(OSError):
                    if kind == "page":
                        self.r.capture_response(ws, newer["scope_id"], {"jobs": [gh_job(description="NEW operations leadership.")]}, now=NOW)
                    else:
                        self.r.resolve_pointer(ws, newer["scope_id"], source_record_id="1", now=NOW, record={
                            "source": "greenhouse", "source_record_id": "1", "employer": "Example", "title": "Operations Lead 1",
                            "posting_url": "https://example.test/jobs/1", "raw": {"description": "NEW operations leadership."}})
                recovered = self.r.replay_scope(ws, newer["scope_id"], now=LATER)
                self.assertFalse(recovered["complete"])
                conflict = next(p for p in recovered["pending"] if p["reason"] == "capture_time_conflict")
                self.assertEqual(conflict["review_id"], row["review_id"])
                self.assertIn("later timestamp", conflict["next_action"])
                self.assertIn("new scope", conflict["next_action"])
                held = q.load_queue(ws)["items"][row["review_id"]]
                for field in ("active_snapshot_hash", "content_hash", "decision", "revision", "history", "last_seen_at"):
                    self.assertEqual(held[field], before[field], field)
                self.assertEqual(len(held["observations"]), 2)
                self.assertFalse(q.summary(ws, now=LATER)["complete"])
                with self.assertRaisesRegex(ValueError, "review_queue_incomplete"):
                    merge_discovery_state(ws, DiscoveryState(), (("greenhouse", SourceResult(True, LATER, ("1",), None,
                        intake_ids=tuple(recovered["intake_ids"]), coverage_scope_ids=(newer["scope_id"],))),))
                self.assertFalse((ws.state / "discovery-state.json").exists())
                evidence = {path: path.read_bytes() for path in (ws.sources / "discovery-retrieval").glob("*.json")}
                self.r.replay_scope(ws, newer["scope_id"], now=LATER)
                self.assertEqual(q.load_queue(ws)["items"][row["review_id"]], held)

                fresh = self.r.register_scope(ws, run_id="fresh-after-conflict", source="greenhouse", provider="greenhouse",
                    query={"board": "example", "employer": "Example"}, now=LATER)
                fresh = self.r.capture_response(ws, fresh["scope_id"], {"jobs": [gh_job(description="NEW operations leadership.")]}, now=LATER)
                current = q.next_items(ws, now=LATER)[0]
                self.assertEqual(current["raw"]["description"], "NEW operations leadership.")
                self.assertIsNone(current["decision"])
                self.assertNotIn("capture_time_conflict", current)
                self.assertEqual(current["history"][-1]["decision"], before["decision"])
                q.record_decision(ws, current["review_id"], {"status": "non_match",
                    "rationale": "The newly captured requirements still exceed the approved profile.", "evidence": [current["posting_url"]]},
                    expected_revision=current["revision"], expected_context=current["expected_context"], now=LATER)
                q.validate_delivery(ws, {"source_results": {"greenhouse": {
                    "success": True, "completed_at": LATER, "coverage_scope_ids": [fresh["scope_id"]],
                    "seen_records": fresh["source_record_ids"], "intake_ids": fresh["intake_ids"]}}}, now=LATER)
                for path, original in evidence.items():
                    self.assertEqual(path.read_bytes(), original)

    def test_public_ats_aggregate_accepts_registered_board_source_alias(self):
        scope = self.capture(self.scope(source="example-company-board"))
        self.decide_all()
        q.validate_delivery(self.ws, {"source_results": {"public_ats": self.result(scope)}}, now=LATER)

    def test_unstructured_capture_preserves_unknown_count_and_extracted_pointer(self):
        scope = self.scope("unstructured", source="web-search", query={"query": "operations"})
        native = {"results": [{"url": "https://example.test/jobs/1", "title": "Operations Lead 1"}]}
        scope = self.r.capture_response(self.ws, scope["scope_id"], native, now=NOW)
        self.assertFalse(scope["complete"])
        self.assertFalse(scope["returned_count_known"])
        record = {"source": "web-search", "source_record_id": "1", "employer": "Example",
            "title": "Operations Lead 1", "posting_url": "https://example.test/jobs/1", "raw": {}}
        scope = self.r.capture_response(self.ws, scope["scope_id"], {"raw_response": native, "extracted_listings": [record]}, now=NOW)
        self.assertEqual(scope["returned_records"], 1)
        self.assertEqual(len(scope["unresolved_pointers"]), 1)
        scope = self.r.resolve_pointer(self.ws, scope["scope_id"], source_record_id="1",
            record={**record, "raw": {"description": "Full employer description now available."}}, now=NOW)
        self.assertEqual(scope["unresolved_pointers"], [])
        self.assertFalse(scope["complete"])
        self.assertTrue(any(p["reason"] == "unstructured_source_not_enumerable" for p in scope["pending"]))
        with self.assertRaisesRegex(ValueError, "retrieval"):
            self.r.validate_source_result(self.ws, "public_ats", self.result(scope), now=LATER)

    def test_known_source_brand_cannot_claim_another_provider_contract(self):
        for source, provider in (("indeed", "ashby"), ("greenhouse", "lever"), ("public_ats", "unstructured")):
            with self.subTest(source=source, provider=provider), self.assertRaisesRegex(ValueError, "source_provider"):
                self.scope(provider, source=source)
        self.assertEqual(self.r.load_ledger(self.ws)["scopes"], {})

    def test_pointer_fetch_failure_resolves_without_losing_failure_history(self):
        scope = self.capture(self.scope(), [gh_job(description="")])
        scope = self.r.record_failure(self.ws, scope["scope_id"], now=NOW,
            reason="description_fetch_failed", next_action="Retry the missing official job description.")
        self.assertFalse(scope["complete"])
        scope = self.r.resolve_pointer(self.ws, scope["scope_id"], source_record_id="1", now=NOW,
            record={"source": "greenhouse", "source_record_id": "1", "employer": "Example",
                "title": "Operations Lead 1", "posting_url": "https://example.test/jobs/1",
                "raw": {"description": "The official job description was retrieved on retry."}})
        self.assertTrue(scope["complete"])
        self.assertEqual(scope["unresolved_pointers"], [])
        self.assertNotIn("failure", scope)
        self.assertEqual(len(scope["failures"]), 1)
        self.assertEqual(scope["failures"][0]["reason"], "description_fetch_failed")
        self.decide_all()
        result = self.result(scope)
        result["coverage_scope_ids"] = tuple(result["coverage_scope_ids"])
        result["intake_ids"] = tuple(result["intake_ids"])
        result["seen_records"] = tuple(result["seen_records"])
        merged = merge_discovery_state(self.ws, DiscoveryState(), (("greenhouse", SourceResult(**result)),))
        self.assertEqual(merged.sources["greenhouse"].seen_records, ("1",))

    def test_resolving_pointer_does_not_clear_failed_page_continuation(self):
        scope = self.scope("lever", query={"board": "example", "employer": "Example", "page_size": 1})
        scope = self.r.capture_response(self.ws, scope["scope_id"], [{"id": "1", "text": "Operations",
            "hostedUrl": "https://example.test/jobs/1", "descriptionPlain": ""}], now=NOW)
        self.r.record_failure(self.ws, scope["scope_id"], now=NOW,
            reason="continuation_fetch_failed", next_action="Retry the provider page at cursor 1.")
        self.r.record_failure(self.ws, scope["scope_id"], now=NOW, source_record_id="1",
            reason="description_timeout", next_action="Retry this missing official description.")
        scope = self.r.resolve_pointer(self.ws, scope["scope_id"], source_record_id="1", now=NOW,
            record={"source": "lever", "source_record_id": "1", "employer": "Example",
                "title": "Operations", "posting_url": "https://example.test/jobs/1",
                "raw": {"description": "Full description."}})
        self.assertEqual(scope["failure"]["reason"], "continuation_fetch_failed")
        self.assertEqual(scope["next_cursor"], "1")
        self.assertFalse(scope["complete"])

    def test_malformed_page_with_returned_job_cannot_be_retired_by_empty_retry(self):
        scope = self.scope()
        bad = {"jobs": [gh_job(), None], "meta": {"total": 2}}
        scope = self.r.capture_response(self.ws, scope["scope_id"], bad, now=NOW)
        scope = self.capture(scope, [])
        self.assertFalse(scope["complete"])
        self.assertFalse(scope["returned_count_known"])
        self.assertTrue(any("1" in p.get("source_record_ids", []) for p in scope["pending"]))
        with self.assertRaisesRegex(ValueError, "retrieval"):
            self.r.validate_source_result(self.ws, "greenhouse", self.result(scope), now=LATER)

    def test_malformed_metadata_can_retry_only_with_original_ids_and_consistent_count(self):
        scope = self.scope()
        bad = {"jobs": [gh_job()], "meta": {"total": "malformed"}}
        self.r.capture_response(self.ws, scope["scope_id"], bad, now=NOW)
        scope = self.capture(scope)
        self.assertTrue(scope["complete"])

    def test_retry_cannot_hide_changed_total_from_invalid_original_page(self):
        scope = self.scope()
        self.r.capture_response(self.ws, scope["scope_id"], {"jobs": [gh_job()], "meta": {"total": 2}}, now=NOW)
        scope = self.capture(scope)
        self.assertFalse(scope["complete"])

    def test_explicit_pointer_failure_recovers_for_supplementary_and_nonterminal_sources(self):
        for provider in ("indeed", "unstructured", "lever"):
            with self.subTest(provider=provider):
                scope = self.scope(provider, query={"board": "example", "employer": "Example", "page_size": 1})
                record = {"source": provider, "source_record_id": "1", "employer": "Example",
                    "title": "Operations", "posting_url": "https://example.test/jobs/1", "raw": {}}
                response = {"jobs": [{"jrtk": "1", "title": "Operations", "company": "Example",
                    "url": "https://example.test/jobs/1"}]}
                if provider == "unstructured":
                    response = {"raw_response": response, "extracted_listings": [record]}
                elif provider == "lever":
                    response = [{"id": "1", "text": "Operations", "hostedUrl": "https://example.test/jobs/1"}]
                scope = self.r.capture_response(self.ws, scope["scope_id"], response, now=NOW)
                self.assertFalse(scope["exhausted"])
                self.r.record_failure(self.ws, scope["scope_id"], now=NOW, source_record_id="1",
                    reason="description_timeout", next_action="Retry the official description for this listing.")
                scope = self.r.resolve_pointer(self.ws, scope["scope_id"], source_record_id="1", now=NOW,
                    record={**record, "raw": {"description": "Recovered full official job description."}})
                self.assertFalse(scope["complete"])
                self.assertEqual(scope["unresolved_pointers"], [])
                self.assertNotIn("failure", scope)
                self.assertFalse(any(p["reason"] == "description_timeout" for p in scope["pending"]))
                self.assertEqual(scope["failures"][0]["pending_pointer_ids"], ["1"])

    def test_explicit_failure_target_must_be_an_existing_unresolved_pointer(self):
        scope = self.capture(self.scope(), [gh_job(description="")])
        path = self.ws.state / "discovery-retrieval.json"
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "pointer"):
            self.r.record_failure(self.ws, scope["scope_id"], now=NOW, source_record_id="unknown",
                reason="description_timeout", next_action="Retry the description.")
        self.assertEqual(path.read_bytes(), before)

    def test_multiple_explicit_pointer_failures_recover_independently(self):
        scope = self.capture(self.scope(), [gh_job(1, ""), gh_job(2, "")])
        for number in (1, 2):
            self.r.record_failure(self.ws, scope["scope_id"], now=NOW, source_record_id=str(number),
                reason=f"description_{number}_timeout", next_action="Retry the description for this listing.")
        for number in (2, 1):
            scope = self.r.resolve_pointer(self.ws, scope["scope_id"], source_record_id=str(number), now=NOW,
                record={"source": "greenhouse", "source_record_id": str(number), "employer": "Example",
                    "title": f"Operations Lead {number}", "posting_url": f"https://example.test/jobs/{number}",
                    "raw": {"description": "Recovered full official job description."}})
            if number == 2:
                self.assertEqual(scope["failure"]["reason"], "description_1_timeout")
                self.assertTrue(any(p["reason"] == "description_1_timeout" for p in scope["pending"]))
                self.assertFalse(any(p["reason"] == "description_2_timeout" for p in scope["pending"]))
        self.assertTrue(scope["complete"])
        self.assertNotIn("failure", scope)
        self.assertEqual(len(scope["failures"]), 2)

    def test_successful_page_retry_preserves_an_unresolved_pointer_failure(self):
        scope = self.scope("lever", query={"board": "example", "employer": "Example", "page_size": 1})
        self.r.capture_response(self.ws, scope["scope_id"], [{"id": "1", "text": "Operations",
            "hostedUrl": "https://example.test/jobs/1"}], now=NOW)
        self.r.record_failure(self.ws, scope["scope_id"], now=NOW,
            reason="page_timeout", next_action="Retry the next page.")
        self.r.record_failure(self.ws, scope["scope_id"], now=NOW, source_record_id="1",
            reason="description_timeout", next_action="Retry this job description.")
        scope = self.r.capture_response(self.ws, scope["scope_id"], [], cursor="1", now=NOW)
        self.assertTrue(scope["exhausted"])
        self.assertEqual(scope["failure"]["reason"], "description_timeout")
        self.assertFalse(any(p["reason"] == "page_timeout" for p in scope["pending"]))
        self.assertTrue(any(p["reason"] == "description_timeout" for p in scope["pending"]))
        self.assertFalse(scope["complete"])
        self.assertEqual(len(scope["failures"]), 2)


if __name__ == "__main__":
    unittest.main()
