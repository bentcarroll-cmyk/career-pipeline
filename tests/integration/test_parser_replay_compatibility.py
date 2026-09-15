"""A parser EOF correction must preserve historical native-capture receipts."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from career_pipeline import retrieval, review_queue
from career_pipeline.atomic import atomic_write_json
from career_pipeline.workspace import create_workspace
from tests.unit.test_source_pages import indeed_response


NOW = "2026-09-15T12:00:00Z"
LATER = "2026-09-15T13:00:00Z"
DESCRIPTION = "Lead the organization.\nBuild measurable customer outcomes.\nOwn the P&L."
RECORD_ID = "JOBSEARCH_synthetic"


class ParserReplayCompatibilityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = create_workspace(Path(temp.name))

    def legacy_capture(self, *, resolved=False, native_description=DESCRIPTION, old_description=""):
        """Write the literal pre-EOF ledger shape using real snapshots and intake."""
        scope = retrieval.register_scope(
            self.workspace, run_id="legacy-capture", source="indeed", provider="indeed",
            query={"search": "operations", "location": "Remote US"}, now=NOW,
        )
        response = indeed_response(native_description)
        native_row = response["structuredContent"]["jobs"][0]
        pointer = {
            "source": "indeed", "source_record_id": RECORD_ID,
            "employer": "Example Cooperative", "title": "Operations Lead",
            "location": "Remote US", "requisition_id": None,
            "posting_url": "https://www.indeed.com/viewjob?jk=synthetic",
            "raw": {**native_row, "provider_description": native_description, "description": old_description},
        }
        initial_queue = review_queue.ingest(self.workspace, [pointer] if old_description else [], source="indeed", now=NOW)
        page_receipt_id = next(iter(initial_queue["intake_batches"]))
        page = {**retrieval._snapshot(self.workspace, response), "cursor": None,
                "captured_at": NOW, "status": "ingested", "intake_ids": [page_receipt_id]}
        scope.update(pages=[page], returned_records=1, returned_record_ids=[RECORD_ID],
                     known_returned_record_ids=[RECORD_ID], ingested_records=1 if old_description else 0,
                     returned_count_known=True, reported_total=840,
                     unresolved_pointers=[] if old_description else [pointer], intake_ids=[page_receipt_id],
                     source_record_ids=[RECORD_ID] if old_description else [],
                     exhausted=False, complete=False)
        if resolved:
            recovered = {**pointer, "raw": {
                "description": "Official description: lead operations, including profit and loss accountability.",
                "resolution_evidence": "https://example.test/careers/operations-lead",
            }}
            ingested = review_queue.ingest(self.workspace, [recovered], source="indeed", now=NOW)
            receipt_id = next(key for key in ingested["intake_batches"] if key != page_receipt_id)
            prepared = review_queue._intake(recovered)
            scope["resolutions"][RECORD_ID] = {
                **retrieval._snapshot(self.workspace, prepared), "captured_at": NOW,
                "status": "ingested", "intake_ids": [receipt_id],
            }
            scope.update(ingested_records=1, unresolved_pointers=[], source_record_ids=[RECORD_ID],
                         intake_ids=sorted([page_receipt_id, receipt_id]))
            row = next(iter(ingested["items"].values()))
            review_queue.record_decision(
                self.workspace, row["review_id"],
                {"status": "non_match", "rationale": "The specialist requirements exceed the synthetic profile.",
                 "evidence": [recovered["raw"]["resolution_evidence"]]},
                expected_revision=row["revision"], expected_context=review_queue.review_context(self.workspace), now=NOW,
            )
        ledger = retrieval.load_ledger(self.workspace)
        ledger["scopes"][scope["scope_id"]] = scope
        atomic_write_json(self.workspace.state / "discovery-retrieval.json", ledger)
        return scope, response, page_receipt_id

    def test_legacy_parse_empty_capture_is_replayed_once_without_losing_original_receipt(self):
        scope, native, old_receipt = self.legacy_capture()
        queue_before = copy.deepcopy(review_queue.load_queue(self.workspace))
        report = retrieval.summary(self.workspace, now=LATER)
        self.assertFalse(any(p["reason"] == "retrieval_evidence_invalid" for p in report["pending"]))
        self.assertEqual(report["returned_records"], 1)
        self.assertEqual(report["ingested_records"], 0)
        self.assertTrue(any("replay" in p["next_action"].lower() for p in report["pending"]))
        self.assertEqual(review_queue.load_queue(self.workspace), queue_before)

        replayed = retrieval.replay_scope(self.workspace, scope["scope_id"], now=LATER)
        self.assertEqual(replayed["returned_records"], 1)
        self.assertEqual(replayed["ingested_records"], 1)
        self.assertEqual(replayed["source_record_ids"], [RECORD_ID])
        self.assertEqual(replayed["unresolved_pointers"], [])
        queue_after = review_queue.load_queue(self.workspace)
        self.assertEqual(queue_after["intake_batches"][old_receipt], queue_before["intake_batches"][old_receipt])
        self.assertEqual(len(queue_after["items"]), 1)
        row = next(iter(queue_after["items"].values()))
        self.assertEqual(len(row["observations"]), 1)
        normalized = json.loads((self.workspace.root / row["observations"][0]["snapshot"]).read_text())
        self.assertEqual(normalized["raw"]["description"], DESCRIPTION)
        self.assertEqual(normalized["raw"]["provider_description"], DESCRIPTION)
        self.assertEqual(json.loads((self.workspace.root / scope["pages"][0]["snapshot"]).read_text()), native)
        retrieval.replay_scope(self.workspace, scope["scope_id"], now=LATER)
        self.assertEqual(review_queue.load_queue(self.workspace), queue_after)

    def test_legacy_resolved_pointer_retains_review_and_resolution_on_replay(self):
        scope, native, _ = self.legacy_capture(resolved=True)
        queue_before = copy.deepcopy(review_queue.load_queue(self.workspace))
        report = retrieval.summary(self.workspace, now=LATER)
        self.assertFalse(any(p["reason"] == "retrieval_evidence_invalid" for p in report["pending"]))
        self.assertEqual(report["returned_records"], 1)
        self.assertEqual(report["ingested_records"], 1)
        self.assertEqual(report["unresolved_pointers"], [])
        for _ in range(2):
            replayed = retrieval.replay_scope(self.workspace, scope["scope_id"], now=LATER)
            self.assertEqual(replayed["returned_records"], 1)
            self.assertEqual(replayed["ingested_records"], 1)
            self.assertEqual(replayed["source_record_ids"], [RECORD_ID])
            self.assertEqual(replayed["intake_ids"], scope["intake_ids"])
        self.assertEqual(review_queue.load_queue(self.workspace), queue_before)
        self.assertEqual(next(iter(queue_before["items"].values()))["status"], "non_match")
        self.assertEqual(json.loads((self.workspace.root / scope["pages"][0]["snapshot"]).read_text()), native)

    def test_legacy_receipt_tampering_still_blocks_parser_compatible_replay(self):
        scope, _, receipt_id = self.legacy_capture(resolved=True)
        queue = review_queue.load_queue(self.workspace)
        queue["intake_batches"][receipt_id]["source_record_ids"] = ["not-the-captured-record"]
        atomic_write_json(self.workspace.state / "discovery-review-queue.json", queue)
        report = retrieval.summary(self.workspace, now=LATER)
        self.assertTrue(any(p["reason"] == "retrieval_evidence_invalid" for p in report["pending"]))
        with self.assertRaisesRegex(ValueError, "retrieval"):
            retrieval.replay_scope(self.workspace, scope["scope_id"], now=LATER)
        self.assertEqual(review_queue.load_queue(self.workspace), queue)

    def test_legacy_truncated_description_replay_preserves_history_and_reopens_review(self):
        scope, native, old_receipt = self.legacy_capture(
            native_description="<p>Lead the organization.</p>Own the P&L.", old_description="Lead the organization.",
        )
        row = next(iter(review_queue.load_queue(self.workspace)["items"].values()))
        review_queue.record_decision(
            self.workspace, row["review_id"],
            {"status": "non_match", "rationale": "The original visible responsibilities did not match the synthetic profile.",
             "evidence": [row["posting_url"]]},
            expected_revision=row["revision"], expected_context=review_queue.review_context(self.workspace), now=NOW,
        )
        queue_before = copy.deepcopy(review_queue.load_queue(self.workspace))
        report = retrieval.summary(self.workspace, now=LATER)
        self.assertFalse(any(p["reason"] == "retrieval_evidence_invalid" for p in report["pending"]))
        self.assertEqual(report["returned_records"], 1)
        self.assertEqual(report["ingested_records"], 1)
        self.assertTrue(any("replay" in p["next_action"].lower() for p in report["pending"]))
        self.assertEqual(review_queue.load_queue(self.workspace), queue_before)

        replayed = retrieval.replay_scope(self.workspace, scope["scope_id"], now=LATER)
        self.assertEqual(replayed["returned_records"], 1)
        self.assertEqual(replayed["ingested_records"], 1)
        queue_after = review_queue.load_queue(self.workspace)
        self.assertEqual(len(queue_after["items"]), 1)
        updated = next(iter(queue_after["items"].values()))
        # Intake, decision, then recovered content each create one revision.
        self.assertEqual(updated["revision"], 3)
        self.assertEqual(updated["status"], "unreviewed")
        self.assertEqual(len(updated["observations"]), 2)
        self.assertEqual(updated["observations"][0], row["observations"][0])
        recovered = json.loads((self.workspace.root / updated["observations"][-1]["snapshot"]).read_text())
        self.assertEqual(recovered["raw"]["description"], "Lead the organization.\nOwn the P&L.")
        self.assertEqual(recovered["raw"]["provider_description"], "<p>Lead the organization.</p>Own the P&L.")
        self.assertEqual(queue_after["intake_batches"][old_receipt], queue_before["intake_batches"][old_receipt])
        self.assertEqual(json.loads((self.workspace.root / scope["pages"][0]["snapshot"]).read_text()), native)
        retrieval.replay_scope(self.workspace, scope["scope_id"], now=LATER)
        self.assertEqual(review_queue.load_queue(self.workspace), queue_after)

    def assert_conflicting_reviewed_description_is_preserved(self, *, captured_at):
        scope, native, _ = self.legacy_capture(
            native_description="<p>Lead the organization.</p>Own the P&L.", old_description="Lead the organization.",
        )
        old = next(iter(review_queue.load_queue(self.workspace)["items"].values()))
        newer = json.loads((self.workspace.root / old["observations"][0]["snapshot"]).read_text())
        newer.pop("raw_field_hash")
        newer["raw"].update(description="New posting: lead research operations and manage a laboratory.",
                            provider_description="New posting: lead research operations and manage a laboratory.")
        queue = review_queue.ingest(self.workspace, [newer], source="indeed", now=captured_at)
        row = next(iter(queue["items"].values()))
        review_queue.record_decision(
            self.workspace, row["review_id"],
            {"status": "non_match", "rationale": "The newer laboratory requirements do not match the synthetic profile.",
             "evidence": [row["posting_url"]]},
            expected_revision=row["revision"], expected_context=review_queue.review_context(self.workspace), now=LATER,
        )
        before = copy.deepcopy(review_queue.load_queue(self.workspace))
        report = retrieval.summary(self.workspace, now=LATER)
        self.assertTrue(any(p["reason"] == "normalization_repair_conflicts_newer_observation" for p in report["pending"]))
        self.assertFalse(report["complete"])
        for _ in range(2):
            replayed = retrieval.replay_scope(self.workspace, scope["scope_id"], now=LATER)
            self.assertEqual(replayed["returned_records"], 1)
            self.assertEqual(replayed["ingested_records"], 1)
        self.assertEqual(review_queue.load_queue(self.workspace), before)
        self.assertEqual(json.loads((self.workspace.root / scope["pages"][0]["snapshot"]).read_text()), native)

    def test_old_normalization_cannot_replace_a_newer_reviewed_description(self):
        self.assert_conflicting_reviewed_description_is_preserved(captured_at=LATER)

    def test_equal_timestamp_changed_observation_blocks_legacy_normalization_replay(self):
        self.assert_conflicting_reviewed_description_is_preserved(captured_at=NOW)

    def assert_interrupted_repair_recovers(self, *, after_ingestion):
        scope, native, _ = self.legacy_capture()
        ingest = review_queue.ingest

        def interrupted(*args, **kwargs):
            if after_ingestion:
                ingest(*args, **kwargs)
            raise RuntimeError("interrupted normalization repair")

        with patch.object(review_queue, "ingest", side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, "interrupted normalization"):
                retrieval.replay_scope(self.workspace, scope["scope_id"], now=LATER)
        saved = retrieval.load_ledger(self.workspace)["scopes"][scope["scope_id"]]
        repair = saved["pages"][0]["normalization_repair"]
        self.assertEqual(repair["status"], "captured")
        self.assertEqual(json.loads((self.workspace.root / repair["snapshot"]).read_text())["records"][0]["raw"]["description"], DESCRIPTION)
        report = retrieval.summary(self.workspace, now=LATER)
        self.assertTrue(any(p["reason"] == "normalization_replay_required" for p in report["pending"]))
        self.assertFalse(any(p["reason"] == "retrieval_evidence_invalid" for p in report["pending"]))
        replayed = retrieval.replay_scope(self.workspace, scope["scope_id"], now=LATER)
        self.assertEqual(replayed["returned_records"], 1)
        self.assertEqual(replayed["ingested_records"], 1)
        queue_after = review_queue.load_queue(self.workspace)
        row = next(iter(queue_after["items"].values()))
        self.assertEqual(row["revision"], 1)
        self.assertEqual(len(row["observations"]), 1)
        self.assertEqual(json.loads((self.workspace.root / scope["pages"][0]["snapshot"]).read_text()), native)
        retrieval.replay_scope(self.workspace, scope["scope_id"], now=LATER)
        self.assertEqual(review_queue.load_queue(self.workspace), queue_after)

    def test_interruption_before_repair_intake_recovers_from_saved_normalization(self):
        self.assert_interrupted_repair_recovers(after_ingestion=False)

    def test_interruption_after_repair_intake_does_not_duplicate_observation(self):
        self.assert_interrupted_repair_recovers(after_ingestion=True)

    def test_new_capture_version_prevents_reinterpretation_as_legacy_empty_parse(self):
        scope = retrieval.register_scope(
            self.workspace, run_id="new-capture", source="indeed", provider="indeed", query={}, now=NOW,
        )
        scope = retrieval.capture_response(self.workspace, scope["scope_id"], indeed_response(DESCRIPTION), now=NOW)
        self.assertEqual(scope["ingested_records"], 1)
        self.assertEqual(scope["pages"][0]["normalization_version"], 2)
        before = copy.deepcopy(review_queue.load_queue(self.workspace))
        ledger = retrieval.load_ledger(self.workspace)
        del ledger["scopes"][scope["scope_id"]]["pages"][0]["normalization_version"]
        atomic_write_json(self.workspace.state / "discovery-retrieval.json", ledger)
        with self.assertRaisesRegex(ValueError, "retrieval_intake_receipt_mismatch"):
            retrieval.replay_scope(self.workspace, scope["scope_id"], now=LATER)
        self.assertEqual(review_queue.load_queue(self.workspace), before)

    def test_legacy_page_version_tampering_blocks_replay_without_queue_writes(self):
        scope, _, _ = self.legacy_capture()
        original = retrieval.load_ledger(self.workspace)
        before = copy.deepcopy(review_queue.load_queue(self.workspace))
        for version in (True, None, 0, 2, 3, "1"):
            with self.subTest(version=version):
                ledger = copy.deepcopy(original)
                ledger["scopes"][scope["scope_id"]]["pages"][0]["normalization_version"] = version
                atomic_write_json(self.workspace.state / "discovery-retrieval.json", ledger)
                with self.assertRaisesRegex(ValueError, "retrieval"):
                    retrieval.replay_scope(self.workspace, scope["scope_id"], now=LATER)
                self.assertEqual(review_queue.load_queue(self.workspace), before)

    def test_repair_version_time_binding_snapshot_and_receipt_tampering_block_replay(self):
        scope, _, _ = self.legacy_capture()
        retrieval.replay_scope(self.workspace, scope["scope_id"], now=LATER)
        original = retrieval.load_ledger(self.workspace)
        before = copy.deepcopy(review_queue.load_queue(self.workspace))
        original_repair = original["scopes"][scope["scope_id"]]["pages"][0]["normalization_repair"]
        forged = json.loads((self.workspace.root / original_repair["snapshot"]).read_text())
        forged["records"][0]["raw"]["description"] = "Forged description absent from the native page."
        forged_ref = retrieval._snapshot(self.workspace, forged)
        cases = (
            {"normalization_version": True}, {"normalization_version": 1}, {"normalization_version": 3},
            {"page_snapshot_hash": "0" * 64}, {"snapshot_hash": "0" * 64},
            {"captured_at": "2026-09-15T11:59:00Z"}, {"captured_at": "2026-09-15T14:00:00Z"},
            {"intake_ids": []}, {"status": "ignored"}, forged_ref,
        )
        for change in cases:
            with self.subTest(change=change):
                ledger = copy.deepcopy(original)
                ledger["scopes"][scope["scope_id"]]["pages"][0]["normalization_repair"].update(change)
                atomic_write_json(self.workspace.state / "discovery-retrieval.json", ledger)
                report = retrieval.summary(self.workspace, now=LATER)
                self.assertTrue(any(p["reason"] == "retrieval_evidence_invalid" for p in report["pending"]))
                with self.assertRaisesRegex(ValueError, "retrieval"):
                    retrieval.replay_scope(self.workspace, scope["scope_id"], now=LATER)
                self.assertEqual(review_queue.load_queue(self.workspace), before)


if __name__ == "__main__":
    unittest.main()
