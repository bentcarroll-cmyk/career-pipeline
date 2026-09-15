from __future__ import annotations

import importlib.util
import copy
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import asdict
from unittest.mock import patch
from pathlib import Path

from career_pipeline.workspace import create_workspace


NOW = "2026-09-14T12:00:00+00:00"
LATER = "2026-09-15T12:00:00+00:00"


def record(number=1, **changes):
    value = dict(source="indeed", source_record_id=f"result-{number}",
                 employer="Example Cooperative", title=f"Operations Lead {number}",
                 location="Remote US", posting_url=f"https://example.test/jobs/{number}",
                 raw={"description": "Lead operations and improve customer workflows.",
                      "salary": "$160000-$220000", "jrtk": f"result-{number}"})
    value.update(changes)
    return value


def decision(status="non_match", **changes):
    value = dict(status=status, rationale="The documented specialist duties do not match the approved evidence.",
                 evidence=["https://example.test/jobs/1"])
    value.update(changes)
    return value


class ReviewQueueTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("career_pipeline.review_queue"),
                             "Discovery must persist and consume unfinished reviews")
        from career_pipeline import review_queue
        self.q = review_queue
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = create_workspace(Path(self.temp.name))

    def test_selected_seven_cannot_complete_eighty_six_returned_candidates(self):
        queue = self.q.ingest(self.ws, [record(i) for i in range(86)], now=NOW)
        for row in list(queue["items"].values())[:7]:
            self.q.record_decision(self.ws, row["review_id"], decision(),
                                   expected_context=self.q.review_context(self.ws), expected_revision=row["revision"], now=NOW)
        summary = self.q.summary(self.ws, now=NOW)
        self.assertEqual(summary["unreviewed"], 79)
        self.assertFalse(summary["complete"])
        self.assertFalse(summary["can_expand_search"])
        with self.assertRaisesRegex(ValueError, "review_queue_incomplete"):
            self.q.validate_delivery(self.ws, {"reviewed": [], "source_results": {
                "indeed": {"success": True}}}, now=NOW)

    def test_source_description_survives_intake_and_snapshot_tampering_fails(self):
        row = next(iter(self.q.ingest(self.ws, [record()], now=NOW)["items"].values()))
        pending = self.q.next_items(self.ws, now=NOW)
        self.assertEqual(pending[0]["raw"]["description"], record()["raw"]["description"])
        path = self.ws.root / row["observations"][0]["snapshot"]
        path.write_text("{}")
        with self.assertRaisesRegex(ValueError, "snapshot_hash_mismatch"):
            self.q.next_items(self.ws, now=NOW)

    def test_generic_deferred_is_not_an_attempted_verification(self):
        row = next(iter(self.q.ingest(self.ws, [record()], now=NOW)["items"].values()))
        for bad in [decision("deferred"), decision("blocked"), decision("blocked", reason_code="review_pending")]:
            with self.assertRaises(ValueError):
                self.q.record_decision(self.ws, row["review_id"], bad,
                                       expected_context=self.q.review_context(self.ws), expected_revision=row["revision"], now=NOW)
        self.assertEqual(self.q.summary(self.ws, now=NOW)["unreviewed"], 1)

    def test_actual_block_has_attempt_evidence_and_becomes_due_again(self):
        row = next(iter(self.q.ingest(self.ws, [record()], now=NOW)["items"].values()))
        blocked = decision("blocked", reason_code="source_unavailable",
                           attempts=[dict(url="https://example.test/jobs/1", checked_at=NOW, result="http_403")],
                           next_action="Retry the official employer page with the approved browser.", retry_after=LATER)
        self.q.record_decision(self.ws, row["review_id"], blocked,
                               expected_context=self.q.review_context(self.ws), expected_revision=row["revision"], now=NOW)
        self.assertEqual(self.q.next_items(self.ws, now=NOW), [])
        self.assertEqual(len(self.q.next_items(self.ws, now=LATER)), 1)
        self.assertFalse(self.q.summary(self.ws, now=NOW)["complete"])
        self.assertEqual(self.q.summary(self.ws, now=NOW)["blocked"], 1)

    def test_new_connector_alias_does_not_erase_a_completed_review(self):
        row = next(iter(self.q.ingest(self.ws, [record()], now=NOW)["items"].values()))
        self.q.record_decision(self.ws, row["review_id"], decision(), expected_context=self.q.review_context(self.ws), expected_revision=row["revision"], now=NOW)
        newer = record(source_record_id="new-alias", raw={**record()["raw"], "jrtk": "new-alias"})
        queue = self.q.ingest(self.ws, [newer], now=LATER)
        self.assertEqual(len(queue["items"]), 2)
        self.assertEqual(self.q.summary(self.ws, now=LATER)["non_match"], 1)
        self.assertEqual(self.q.summary(self.ws, now=LATER)["unreviewed"], 1)

    def test_changed_description_reopens_and_stale_writer_cannot_resolve_it(self):
        row = next(iter(self.q.ingest(self.ws, [record()], now=NOW)["items"].values()))
        changed = record(raw={**record()["raw"], "description": "A materially different role with other duties."})
        self.q.ingest(self.ws, [changed], now=LATER)
        with self.assertRaisesRegex(ValueError, "stale_review_revision"):
            self.q.record_decision(self.ws, row["review_id"], decision(), expected_context=self.q.review_context(self.ws), expected_revision=row["revision"], now=LATER)
        self.assertEqual(self.q.summary(self.ws, now=LATER)["unreviewed"], 1)

    def test_title_match_is_review_hint_and_never_automatic_suppression(self):
        folder = self.ws.jobs / "JOB-000001"
        folder.mkdir()
        (folder / "job.json").write_text(json.dumps(dict(job_id="JOB-000001", employer="Example Cooperative",
                                                       title="Operations Lead 1", requisition_id="OTHER")))
        self.q.ingest(self.ws, [record()], now=NOW)
        row = self.q.next_items(self.ws, now=NOW)[0]
        self.assertEqual(row["possible_existing_job_ids"], ["JOB-000001"])
        self.assertEqual(row["status"], "unreviewed")
        with self.assertRaisesRegex(ValueError, "identity_resolution_required"):
            self.q.record_decision(self.ws, row["review_id"], decision("qualifying"),
                                   expected_context=self.q.review_context(self.ws), expected_revision=row["revision"], now=NOW)

    def test_duplicate_requires_a_reference_and_matching_basis(self):
        row = next(iter(self.q.ingest(self.ws, [record()], now=NOW)["items"].values()))
        with self.assertRaisesRegex(ValueError, "duplicate_reference_required"):
            self.q.record_decision(self.ws, row["review_id"], decision("duplicate"), expected_context=self.q.review_context(self.ws), expected_revision=row["revision"], now=NOW)
        self.q.record_decision(self.ws, row["review_id"], decision("duplicate", existing_reference="JOB-000001",
                               identity_resolution="Exact employer and verified requisition match JOB-000001."),
                               expected_context=self.q.review_context(self.ws), expected_revision=row["revision"], now=NOW)
        self.assertTrue(self.q.summary(self.ws, now=NOW)["review_complete"])

    def test_profile_change_requires_a_fresh_assessment(self):
        profile = self.ws.profile / "Career_Profile.md"
        profile.write_text("Approved synthetic profile")
        row = next(iter(self.q.ingest(self.ws, [record()], now=NOW)["items"].values()))
        self.q.record_decision(self.ws, row["review_id"], decision(), expected_context=self.q.review_context(self.ws), expected_revision=row["revision"], now=NOW)
        profile.write_text("Changed approved synthetic profile")
        self.assertEqual(self.q.summary(self.ws, now=LATER)["unreviewed"], 1)

    def test_invalid_intake_is_atomic_and_does_not_lose_existing_pending(self):
        self.q.ingest(self.ws, [record()], now=NOW)
        before = (self.ws.state / "discovery-review-queue.json").read_bytes()
        with self.assertRaises(ValueError):
            self.q.ingest(self.ws, [record(2), record(3, raw={})], now=LATER)
        self.assertEqual((self.ws.state / "discovery-review-queue.json").read_bytes(), before)

    def test_delivery_cli_rejects_false_completion_before_writing_jobs_or_checkpoint(self):
        self.q.ingest(self.ws, [record()], now=NOW)
        (self.ws.state / "config.json").write_text(json.dumps({"enabled_sources": ["indeed"], "require_review_queue": True}))
        payload = self.ws.root / "reviewed.json"
        payload.write_text(json.dumps({"reviewed": [], "source_results": {"indeed": {
            "success": True, "completed_at": NOW, "seen_records": ["result-1"]}}}))
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run([sys.executable, str(root / "scripts/plan_discovery.py"),
                                 "--workspace", str(self.ws.root), "--reviewed", str(payload),
                                 "--occurred-at", NOW], capture_output=True, text=True)
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertIn("review_queue_incomplete", result.stderr)
        self.assertFalse((self.ws.state / "discovery-state.json").exists())
        self.assertEqual(list(self.ws.jobs.iterdir()), [])

    def test_checkpoint_merge_rechecks_queue_under_lock(self):
        from career_pipeline.checkpoints import DiscoveryState, SourceResult, merge_discovery_state
        (self.ws.state / "config.json").write_text(json.dumps({"require_review_queue": True}))
        self.q.ingest(self.ws, [record()], now=NOW)
        with self.assertRaisesRegex(ValueError, "review_queue_incomplete"):
            merge_discovery_state(self.ws, DiscoveryState(), (("indeed", SourceResult(
                success=True, completed_at=NOW, seen_records=("result-1",), cursor=None)),))
        self.assertFalse((self.ws.state / "discovery-state.json").exists())

    def test_actual_empty_board_can_complete_but_missing_intake_cannot(self):
        from tests.retrieval_fixtures import board_scope
        payload = {"source_results": {"greenhouse": {"success": True}}}
        with self.assertRaisesRegex(ValueError, "review_queue_incomplete"):
            self.q.validate_delivery(self.ws, payload, now=NOW)
        scope = board_scope(self.ws, "greenhouse", [], NOW)
        payload["source_results"]["greenhouse"].update(intake_ids=scope["intake_ids"],
            coverage_scope_ids=[scope["scope_id"]], completed_at=NOW)
        self.q.validate_delivery(self.ws, payload, now=NOW)

    def test_old_snapshot_cannot_deliver_after_changed_content_is_reviewed(self):
        queue = self.q.ingest(self.ws, [record()], now=NOW)
        row = next(iter(queue["items"].values()))
        old = self.q.next_items(self.ws, now=NOW)[0]
        self.q.ingest(self.ws, [record(raw={"description": "Different duties and requirements for this opening."})], now=LATER)
        current = self.q.next_items(self.ws, now=LATER)[0]
        self.q.record_decision(self.ws, row["review_id"], decision("qualifying"), expected_context=self.q.review_context(self.ws), expected_revision=current["revision"], now=LATER)
        with self.assertRaisesRegex(ValueError, "candidate_not_in_review_queue"):
            self.q.validate_delivery(self.ws, {"reviewed": [{"candidate": {
                "source": "indeed", "source_record_id": old["source_record_id"], "raw_field_hash": old["raw_field_hash"]},
                "assessment": {"disposition": "worth_considering"}}]}, now=LATER)

    def test_interrupted_delivery_replays_without_duplicate_job_and_links_queue(self):
        from tests.integration.test_discovery_delivery import create_workspace as approved_workspace, reviewed
        from career_pipeline.checkpoints import DiscoveryState, SourceResult, merge_discovery_state
        from career_pipeline.discovery import deliver_reviewed_jobs
        from tests.retrieval_fixtures import captured_reviewed_item
        ws = approved_workspace(self.ws.root)
        item, scope = captured_reviewed_item(ws, reviewed(1), NOW)
        with patch.object(self.q, "mark_delivered", side_effect=RuntimeError("interrupted after canonical write")):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                deliver_reviewed_jobs(ws, DiscoveryState(), (item,), occurred_at=NOW)
        self.assertEqual(len(list(ws.jobs.glob("*/job.json"))), 1)
        self.assertEqual(self.q.summary(ws, now=NOW)["ready_for_delivery"], 1)
        with self.assertRaisesRegex(ValueError, "review_queue_incomplete"):
            merge_discovery_state(ws, DiscoveryState(), (("public-search", SourceResult(True, NOW, (), None)),))
        outcome = deliver_reviewed_jobs(ws, DiscoveryState(), (item,), occurred_at=NOW)
        self.assertEqual(outcome.created_job_ids, ())
        self.assertTrue(self.q.summary(ws, now=NOW)["complete"])
        self.assertEqual(next(iter(self.q.load_queue(ws)["items"].values()))["job_id"], "JOB-000001")
        merged = merge_discovery_state(ws, outcome.state, (("public-search", SourceResult(True, NOW, (item.candidate.source_record_id,), None,
            tuple(scope["intake_ids"]), (scope["scope_id"],))),))
        self.assertEqual(merged.sources["public-search"].last_successful_at, NOW)

    def test_new_process_resumes_full_pending_description(self):
        self.q.ingest(self.ws, [record()], now=NOW)
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run([sys.executable, str(root / "scripts/review_discovery_queue.py"),
                                 "--workspace", str(self.ws.root), "--occurred-at", LATER, "next"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["unreviewed"], 1)
        self.assertEqual(payload["items"][0]["raw"]["description"], record()["raw"]["description"])

    def test_distinct_req_less_openings_remain_individually_reviewable(self):
        second = record(source_record_id="other-opening", posting_url="https://example.test/jobs/other",
                        raw={"description": "A different opening on another team with other responsibilities."})
        self.q.ingest(self.ws, [record(), second], now=NOW)
        pending = self.q.next_items(self.ws, now=NOW)
        self.assertEqual(len(pending), 2)
        self.assertEqual({r["source_record_id"] for r in pending}, {"result-1", "other-opening"})

    def test_shared_requisition_keeps_distinct_posting_bodies_independently_reviewable(self):
        first = record(requisition_id="shared-442")
        second = record(source_record_id="different-posting", requisition_id="shared-442",
                        posting_url="https://example.test/jobs/different-posting",
                        raw={"description": "Lead classified operations. Active clearance is required."})
        self.q.ingest(self.ws, [first, second], now=NOW)
        pending = self.q.next_items(self.ws, now=NOW)
        self.assertEqual(len(pending), 2)
        self.assertEqual({r["source_record_id"]: r["raw"]["description"] for r in pending}, {
            "result-1": "Lead operations and improve customer workflows.",
            "different-posting": "Lead classified operations. Active clearance is required."})

    def test_shared_requisition_cannot_carry_review_to_another_posting_with_same_body(self):
        first = record(requisition_id="shared-442")
        row = next(iter(self.q.ingest(self.ws, [first], now=NOW)["items"].values()))
        self.q.record_decision(self.ws, row["review_id"], decision("excluded"),
            expected_context=self.q.review_context(self.ws), expected_revision=1, now=NOW)
        second = {**first, "source_record_id": "different-posting",
                  "posting_url": "https://example.test/jobs/different-posting"}
        self.q.ingest(self.ws, [second], now=LATER)
        pending = self.q.next_items(self.ws, now=LATER)
        self.assertEqual([r["source_record_id"] for r in pending], ["different-posting"])
        self.assertEqual(self.q.summary(self.ws, now=LATER)["excluded"], 1)

    def legacy_combined_queue(self):
        """A pre-fix persisted row with two posting IDs and one ambiguous decision."""
        first = record(requisition_id="shared-442")
        second = record(source_record_id="different-posting", requisition_id="shared-442",
                        posting_url="https://example.test/jobs/different-posting",
                        raw={"description": "Lead classified operations. Active clearance is required."})
        queue = self.q.ingest(self.ws, [first, second], now=NOW)
        observations = [o for row in queue["items"].values() for o in row["observations"]]
        # Literal v1 hashes of the two synthetic material bodies above. Older
        # queues did not include the posting URL in their material body hash.
        for observation in observations:
            observation["content_hash"] = {
                "result-1": "5787303dd0f3ad5a3475439e5d40bc4191f38e153b33235edc131351b898f2af",
                "different-posting": "57f84b6cf0db3a95773db756b441b23e41d317ed32a5d9a7f8dcb3f0b78bf1ee",
            }[observation["source_record_id"]]
        original = copy.deepcopy(next(iter(queue["items"].values())))
        original.pop("content_hash_version", None)
        original.pop("active_snapshot_hash", None)
        original.update(review_id="review:" + "a" * 64, observations=observations,
                        content_hash=observations[-1]["content_hash"], revision=7,
                        status="qualifying", decision=decision("qualifying"),
                        approval_fingerprint=self.q.review_context(self.ws), job_id="JOB-000001",
                        history=[{"revision": 3, "decision": decision("excluded"),
                                  "content_hash": observations[0]["content_hash"]}])
        queue["items"] = {original["review_id"]: original}
        (self.ws.state / "discovery-review-queue.json").write_text(json.dumps(queue))
        return original

    def test_legacy_mixed_row_cannot_receive_another_decision(self):
        original = self.legacy_combined_queue()
        with self.assertRaisesRegex(ValueError, "posting_identity_recovery_required"):
            self.q.record_decision(self.ws, original["review_id"], decision("excluded"),
                expected_context=self.q.review_context(self.ws), expected_revision=7, now=LATER)

    def test_legacy_mixed_row_cannot_be_delivered_or_counted_as_reviewed(self):
        original = self.legacy_combined_queue()
        report = self.q.summary(self.ws, now=LATER)
        self.assertEqual(report["unreviewed"], 1)
        self.assertFalse(report["review_complete"])
        latest = original["observations"][-1]
        candidate = {"source": "indeed", "source_record_id": latest["source_record_id"],
                     "raw_field_hash": latest["raw_field_hash"]}
        with self.assertRaisesRegex(ValueError, "candidate_review_not_completed"):
            self.q.validate_delivery(self.ws, {"reviewed": [{"candidate": candidate,
                "assessment": {"disposition": "worth_considering"}}]}, now=LATER)
        with self.assertRaisesRegex(ValueError, "posting_identity_recovery_required"):
            self.q.next_items(self.ws, now=LATER)

    def test_recovery_cli_plans_without_writing_then_losslessly_splits_and_replays(self):
        original = self.legacy_combined_queue()
        path = self.ws.state / "discovery-review-queue.json"
        before = path.read_bytes()
        original_queue = json.loads(before)
        folder = self.ws.jobs / "JOB-000001"
        folder.mkdir()
        canonical = folder / "job.json"
        canonical.write_text('{"job_id":"JOB-000001","application_status":"applied"}')
        application = self.ws.root / "Applications" / "receipt.json"
        application.parent.mkdir(exist_ok=True)
        application.write_text('{"submission":"confirmed","job_id":"JOB-000001"}')
        script = Path(__file__).resolve().parents[2] / "scripts/review_discovery_queue.py"
        planned = subprocess.run([sys.executable, str(script), "--workspace", str(self.ws.root),
            "--occurred-at", LATER, "plan-recovery"], capture_output=True, text=True)
        self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertEqual(path.read_bytes(), before)
        plan = json.loads(planned.stdout)
        self.assertEqual(plan["review_ids"], [original["review_id"]])
        self.assertEqual(plan["splits"][0]["source_record_ids"], ["different-posting", "result-1"])
        recovery_input = self.ws.root / "recovery-plan.json"
        recovery_input.write_text(json.dumps(plan))
        recovered = subprocess.run([sys.executable, str(script), "--workspace", str(self.ws.root),
            "--occurred-at", LATER, "recover", "--input", str(recovery_input)], capture_output=True, text=True)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        queue = self.q.load_queue(self.ws)
        self.assertEqual(queue["identity_recovery_history"][original["review_id"]]["original_item"], original)
        self.assertEqual(queue["intake_batches"], original_queue["intake_batches"])
        self.assertEqual(queue["intakes"], original_queue["intakes"])
        self.assertEqual(len(queue["items"]), 2)
        self.assertCountEqual([o for row in queue["items"].values() for o in row["observations"]], original["observations"])
        pending = self.q.next_items(self.ws, now=LATER)
        self.assertEqual({row["source_record_id"]: row["raw"]["description"] for row in pending}, {
            "result-1": "Lead operations and improve customer workflows.",
            "different-posting": "Lead classified operations. Active clearance is required."})
        for row in pending:
            self.assertIsNone(row["decision"])
            self.assertNotIn("job_id", row)
            self.assertEqual(row["status"], "unreviewed")
            self.assertGreater(row["revision"], original["revision"])
        # Replay after a new decision must not reopen or replace that decision.
        row = pending[0]
        self.q.record_decision(self.ws, row["review_id"], decision("excluded"),
            expected_context=row["expected_context"], expected_revision=row["revision"], now=LATER)
        after_decision = path.read_bytes()
        replayed = self.q.recover_posting_identities(self.ws, review_ids=plan["review_ids"],
            expected_queue_hash=plan["expected_queue_hash"], now=LATER)
        self.assertTrue(replayed["replayed"])
        self.assertEqual(path.read_bytes(), after_decision)
        self.assertEqual(canonical.read_text(), '{"job_id":"JOB-000001","application_status":"applied"}')
        self.assertEqual(application.read_text(), '{"submission":"confirmed","job_id":"JOB-000001"}')

    def test_recovery_rejects_stale_plan_and_tampered_snapshot_without_queue_write(self):
        original = self.legacy_combined_queue()
        plan = self.q.plan_posting_identity_recovery(self.ws)
        self.q.ingest(self.ws, [record(9)], now=LATER)
        path = self.ws.state / "discovery-review-queue.json"
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "stale_recovery_plan"):
            self.q.recover_posting_identities(self.ws, review_ids=plan["review_ids"],
                expected_queue_hash=plan["expected_queue_hash"], now=LATER)
        self.assertEqual(path.read_bytes(), before)
        plan = self.q.plan_posting_identity_recovery(self.ws)
        snapshot = self.ws.root / original["observations"][-1]["snapshot"]
        snapshot.write_text("{}")
        with self.assertRaisesRegex(ValueError, "snapshot_hash_mismatch"):
            self.q.recover_posting_identities(self.ws, review_ids=plan["review_ids"],
                expected_queue_hash=plan["expected_queue_hash"], now=LATER)
        self.assertEqual(path.read_bytes(), before)

    def test_recovery_is_bounded_and_does_not_change_an_unrelated_decision(self):
        original = self.legacy_combined_queue()
        queue = self.q.ingest(self.ws, [record(9)], now=LATER)
        unrelated = next(row for row in queue["items"].values() if row["review_id"] != original["review_id"])
        decided = self.q.record_decision(self.ws, unrelated["review_id"], decision("excluded"),
            expected_context=self.q.review_context(self.ws), expected_revision=1, now=LATER)
        plan = self.q.plan_posting_identity_recovery(self.ws, review_ids=[original["review_id"]])
        self.q.recover_posting_identities(self.ws, review_ids=plan["review_ids"],
            expected_queue_hash=plan["expected_queue_hash"], now=LATER)
        self.assertEqual(self.q.load_queue(self.ws)["items"][unrelated["review_id"]], decided)

    def test_same_handle_in_different_posting_context_does_not_inherit_decision(self):
        row = next(iter(self.q.ingest(self.ws, [record(requisition_id="same")], now=NOW)["items"].values()))
        self.q.record_decision(self.ws, row["review_id"], decision("excluded"),
            expected_context=self.q.review_context(self.ws), expected_revision=1, now=NOW)
        self.q.ingest(self.ws, [record(employer="Another Employer", requisition_id="same")], now=LATER)
        pending = self.q.next_items(self.ws, now=LATER)
        self.assertEqual([r["employer"] for r in pending], ["Another Employer"])

    def test_url_contradiction_reopens_even_when_raw_body_is_unchanged(self):
        row = next(iter(self.q.ingest(self.ws, [record()], now=NOW)["items"].values()))
        self.q.record_decision(self.ws, row["review_id"], decision("excluded"),
            expected_context=self.q.review_context(self.ws), expected_revision=1, now=NOW)
        self.q.ingest(self.ws, [record(posting_url="https://example.test/jobs/other")], now=LATER)
        pending = self.q.next_items(self.ws, now=LATER)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["posting_url"], "https://example.test/jobs/other")

    def test_old_url_candidate_cannot_deliver_after_current_url_is_reviewed(self):
        self.q.ingest(self.ws, [record()], now=NOW)
        old = self.q.next_items(self.ws, now=NOW)[0]
        self.q.ingest(self.ws, [record(posting_url="https://example.test/jobs/other")], now=LATER)
        current = self.q.next_items(self.ws, now=LATER)[0]
        self.q.record_decision(self.ws, current["review_id"], decision("qualifying"),
            expected_context=current["expected_context"], expected_revision=current["revision"], now=LATER)
        with self.assertRaisesRegex(ValueError, "candidate_not_in_review_queue"):
            self.q.validate_delivery(self.ws, {"reviewed": [{"candidate": old,
                "assessment": {"disposition": "worth_considering"}}]}, now=LATER)
        self.q.validate_delivery(self.ws, {"reviewed": [{"candidate": current,
            "assessment": {"disposition": "worth_considering"}}]}, now=LATER)

    def test_mark_delivered_rejects_mixed_rows_without_changing_old_job_reference(self):
        original = self.legacy_combined_queue()
        latest = original["observations"][-1]
        before = (self.ws.state / "discovery-review-queue.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "posting_identity_recovery_required"):
            self.q.mark_delivered(self.ws, {"source": "indeed", "source_record_id": latest["source_record_id"],
                "raw_field_hash": latest["raw_field_hash"]}, "JOB-000099")
        self.assertEqual((self.ws.state / "discovery-review-queue.json").read_bytes(), before)

    def test_nonqualifying_delivery_keeps_prior_canonical_reference_only_in_history(self):
        row = next(iter(self.q.ingest(self.ws, [record()], now=NOW)["items"].values()))
        row = self.q.record_decision(self.ws, row["review_id"], decision("qualifying"),
            expected_context=self.q.review_context(self.ws), expected_revision=1, now=NOW)
        candidate = self.q.next_items(self.ws, now=NOW)[0]
        self.q.mark_delivered(self.ws, candidate, "JOB-000001")
        self.q.record_decision(self.ws, row["review_id"], decision("non_match"),
            expected_context=self.q.review_context(self.ws), expected_revision=row["revision"], now=LATER)
        before = (self.ws.state / "discovery-review-queue.json").read_bytes()
        # Canonical delivery can still resolve the prior job for this candidate;
        # the non-match must not acquire an active qualifying-delivery marker.
        self.q.mark_delivered(self.ws, candidate, "JOB-000001")
        self.assertEqual((self.ws.state / "discovery-review-queue.json").read_bytes(), before)
        current = self.q.load_queue(self.ws)["items"][row["review_id"]]
        self.assertNotIn("job_id", current)
        self.assertEqual(current["history"][-1]["job_id"], "JOB-000001")

    def test_identical_reingestion_preserves_single_id_legacy_review_and_reference(self):
        queue = self.q.ingest(self.ws, [record(requisition_id="shared-442")], now=NOW)
        row = next(iter(queue["items"].values()))
        row.pop("content_hash_version", None)
        row["content_hash"] = row["observations"][0]["content_hash"] = "5787303dd0f3ad5a3475439e5d40bc4191f38e153b33235edc131351b898f2af"
        row["review_id"] = "review:" + "b" * 64
        queue["items"] = {row["review_id"]: row}
        (self.ws.state / "discovery-review-queue.json").write_text(json.dumps(queue))
        decided = self.q.record_decision(self.ws, row["review_id"], decision("excluded"),
            expected_context=self.q.review_context(self.ws), expected_revision=1, now=NOW)
        recaptured = self.q.ingest(self.ws, [record(requisition_id="shared-442")], now=LATER)
        self.assertEqual(list(recaptured["items"]), ["review:" + "b" * 64])
        current = recaptured["items"][row["review_id"]]
        self.assertEqual(current["decision"], decided["decision"])
        self.assertEqual(current["revision"], 2)
        self.assertEqual(self.q.next_items(self.ws, now=LATER), [])

    def test_recovery_keeps_original_provider_receipts_auditable(self):
        from tests.retrieval_fixtures import board_scope
        from career_pipeline import retrieval
        scope = board_scope(self.ws, "greenhouse", [
            {"id": "posting-a", "title": "Operations Lead", "requisition_id": "shared-442",
             "absolute_url": "https://example.test/jobs/a", "location": {"name": "Remote US"},
             "content": "Lead operations and customer workflows."},
            {"id": "posting-b", "title": "Operations Lead", "requisition_id": "shared-442",
             "absolute_url": "https://example.test/jobs/b", "location": {"name": "Remote US"},
             "content": "Lead classified operations with an active clearance."},
        ], NOW)
        queue = self.q.load_queue(self.ws)
        rows = list(queue["items"].values())
        mixed = copy.deepcopy(rows[0])
        mixed.update(review_id="review:" + "c" * 64,
                     observations=[o for row in rows for o in row["observations"]])
        queue["items"] = {mixed["review_id"]: mixed}
        (self.ws.state / "discovery-review-queue.json").write_text(json.dumps(queue))
        plan = self.q.plan_posting_identity_recovery(self.ws)
        self.q.recover_posting_identities(self.ws, review_ids=plan["review_ids"],
            expected_queue_hash=plan["expected_queue_hash"], now=LATER)
        self.assertTrue(retrieval.summary(self.ws, now=LATER)["complete"])
        for row in self.q.next_items(self.ws, now=LATER):
            self.q.record_decision(self.ws, row["review_id"], decision("excluded"),
                expected_context=row["expected_context"], expected_revision=row["revision"], now=LATER)
        self.q.validate_delivery(self.ws, {"source_results": {"greenhouse": {
            "success": True, "completed_at": LATER, "seen_records": ["posting-a", "posting-b"],
            "intake_ids": scope["intake_ids"], "coverage_scope_ids": [scope["scope_id"]]}}}, now=LATER)

    def alternating_legacy_queue(self, *, ambiguous_other=False):
        first = record(requisition_id="shared-442", raw={"description": "CURRENT role permits remote work."})
        other = record(source_record_id="different-posting", requisition_id="shared-442",
                       posting_url="https://example.test/other", raw={"description": "Another role."})
        stale = {**first, "raw": {"description": "STALE role requires relocation."}}
        captures = [first, other, stale]
        if ambiguous_other:
            captures.extend([{**other, "raw": {"description": "Uncertain alternate role requires relocation."}}, other])
        captures.append(first)
        for minute, item in enumerate(captures):
            review_queue = self.q.ingest(self.ws, [item], now=f"2026-09-14T12:{minute:02}:00+00:00")
        rows = list(review_queue["items"].values())
        original = copy.deepcopy(next(r for r in rows if r["observations"][0]["source_record_id"] == "result-1"))
        original.pop("active_snapshot_hash", None)  # Older queues lacked an exact current-snapshot pointer.
        original.update(review_id="review:" + "f" * 64,
                        observations=[o for row in rows for o in row["observations"]])
        review_queue["items"] = {original["review_id"]: original}
        (self.ws.state / "discovery-review-queue.json").write_text(json.dumps(review_queue))
        return original

    def test_recovery_preserves_current_a_after_a_b_a_reuses_an_old_snapshot(self):
        original = self.alternating_legacy_queue()
        plan = self.q.plan_posting_identity_recovery(self.ws)
        self.q.recover_posting_identities(self.ws, review_ids=plan["review_ids"],
            expected_queue_hash=plan["expected_queue_hash"], now=LATER)
        pending = {row["source_record_id"]: row for row in self.q.next_items(self.ws, now=LATER)}
        self.assertEqual(pending["result-1"]["raw"]["description"], "CURRENT role permits remote work.")
        self.assertCountEqual([o for row in self.q.load_queue(self.ws)["items"].values()
                              for o in row["observations"]], original["observations"])

    def test_reused_snapshot_is_current_without_mutating_original_observation(self):
        first = record(raw={**record()["raw"], "posted_date": "2026-09-01"})
        second = record(raw={**record()["raw"], "posted_date": "2026-09-02"})
        initial = next(iter(self.q.ingest(self.ws, [first], now=NOW)["items"].values()))
        original_observation = copy.deepcopy(initial["observations"][0])
        self.q.ingest(self.ws, [second], now="2026-09-14T13:00:00+00:00")
        self.q.ingest(self.ws, [first], now=LATER)
        pending = self.q.next_items(self.ws, now=LATER)[0]
        self.assertEqual(pending["raw"]["posted_date"], "2026-09-01")
        self.assertEqual(pending["observations"][0], original_observation)

    def test_old_intake_preserves_current_state_after_a_snapshot_has_been_reused(self):
        first = record(raw={"description": "CURRENT remote duties."})
        older = record(raw={"description": "STALE office-only duties."})
        self.q.ingest(self.ws, [first], now=NOW)
        self.q.ingest(self.ws, [older], now="2026-09-14T13:00:00+00:00")
        self.q.ingest(self.ws, [first], now=LATER)
        pending = self.q.next_items(self.ws, now=LATER)[0]
        self.q.record_decision(self.ws, pending["review_id"], decision(), expected_revision=pending["revision"],
            expected_context=pending["expected_context"], now=LATER)
        before = copy.deepcopy(self.q.load_queue(self.ws)["items"][pending["review_id"]])
        self.q.ingest(self.ws, [older], now="2026-09-14T14:00:00+00:00")
        actual = self.q.load_queue(self.ws)["items"][pending["review_id"]]
        self.assertEqual(actual, before)
        self.assertEqual(self.q.next_items(self.ws, now=LATER), [])

    def test_equal_time_conflict_preserves_history_until_strictly_later_capture(self):
        from tests.unit.test_review_location_prefilter import approve_location_scope
        approve_location_scope(self.ws)
        first = record()
        conflicting = record(raw={"description": "Changed responsibilities for this posting."})
        self.q.ingest(self.ws, [first], now=NOW)
        row = self.q.next_items(self.ws, now=NOW)[0]
        self.q.record_decision(self.ws, row["review_id"], decision("qualifying"),
            expected_revision=row["revision"], expected_context=row["expected_context"], now=NOW)
        self.q.mark_delivered(self.ws, row, "JOB-000001")
        before = copy.deepcopy(self.q.load_queue(self.ws)["items"][row["review_id"]])

        self.q.ingest(self.ws, [first], now=NOW, replay=True)
        self.assertEqual(self.q.load_queue(self.ws)["items"][row["review_id"]], before)
        self.q.ingest(self.ws, [conflicting], now=NOW, replay=True)
        held = self.q.load_queue(self.ws)["items"][row["review_id"]]
        self.assertIn("capture_time_conflict", held)
        for field in ("content_hash", "active_snapshot_hash", "decision", "job_id", "revision", "history", "last_seen_at"):
            self.assertEqual(held[field], before[field], field)
        self.assertEqual(self.q.summary(self.ws, now=LATER)["unreviewed"], 1)
        with self.assertRaisesRegex(ValueError, "capture_time_conflict_requires_fresh_capture"):
            self.q.next_items(self.ws, now=LATER)
        with self.assertRaisesRegex(ValueError, "capture_time_conflict_requires_fresh_capture"):
            self.q.record_decision(self.ws, row["review_id"], decision(), expected_revision=held["revision"],
                expected_context=row["expected_context"], now=LATER)
        with self.assertRaisesRegex(ValueError, "capture_time_conflict_requires_fresh_capture"):
            self.q.mark_delivered(self.ws, row, "JOB-000002")
        self.assertEqual(self.q.apply_location_prefilter(self.ws, now=LATER)["held"]["capture_time_conflict"], 1)
        self.q.ingest(self.ws, [conflicting], now=NOW, replay=True)
        self.q.ingest(self.ws, [first], now=NOW)
        self.assertEqual(self.q.load_queue(self.ws)["items"][row["review_id"]], held)

        # Reobserving the original body at a strictly later time also resolves
        # the ambiguity, while preserving the old decision and link in history.
        receipts = copy.deepcopy(self.q.load_queue(self.ws)["intake_batches"])
        self.q.ingest(self.ws, [first], now=LATER)
        recovered = self.q.next_items(self.ws, now=LATER)[0]
        self.assertNotIn("capture_time_conflict", recovered)
        self.assertEqual(recovered["status"], "unreviewed")
        self.assertIsNone(recovered["decision"])
        self.assertNotIn("job_id", recovered)
        self.assertEqual(recovered["history"][-1]["decision"], before["decision"])
        self.assertEqual(recovered["history"][-1]["job_id"], "JOB-000001")
        self.assertEqual(recovered["history"][-1]["capture_time_conflict"], held["capture_time_conflict"])
        self.assertEqual(recovered["observations"], held["observations"])
        for key, receipt in receipts.items():
            self.assertEqual(self.q.load_queue(self.ws)["intake_batches"][key], receipt)
        self.q.ingest(self.ws, [conflicting], now=NOW, replay=True)
        self.assertEqual(self.q.next_items(self.ws, now=LATER)[0], recovered)

    def test_legacy_url_round_trip_retains_a_matching_versioned_observation(self):
        initial = self.q.ingest(self.ws, [record()], now=NOW)
        row = next(iter(initial["items"].values()))
        row.pop("content_hash_version")
        row.pop("active_snapshot_hash")
        row["content_hash"] = row["observations"][0]["content_hash"] = "5787303dd0f3ad5a3475439e5d40bc4191f38e153b33235edc131351b898f2af"
        legacy = copy.deepcopy(row["observations"][0])
        (self.ws.state / "discovery-review-queue.json").write_text(json.dumps(initial))
        self.q.ingest(self.ws, [record(posting_url="https://example.test/changed-route")], now="2026-09-14T13:00:00+00:00")
        self.q.ingest(self.ws, [record()], now=LATER)
        row = next(iter(self.q.load_queue(self.ws)["items"].values()))
        self.assertTrue(any(o["content_hash"] == row["content_hash"] and o["snapshot_hash"] == row["active_snapshot_hash"]
                            for o in row["observations"]), "The active URL must retain a usable observation under version 2.")
        self.assertEqual(self.q.next_items(self.ws, now=LATER)[0]["posting_url"], record()["posting_url"])
        self.assertEqual(row["observations"][0], legacy)
        self.q.ingest(self.ws, [record()], now=LATER)
        self.assertEqual(next(iter(self.q.load_queue(self.ws)["items"].values())), row)

        # Simulate the already-stuck state written before this fix, then recover
        # through the same supported recapture rather than rewriting history.
        state = self.q.load_queue(self.ws)
        broken = state["items"][row["review_id"]]
        broken["observations"] = [o for o in broken["observations"] if o == legacy or o["snapshot_hash"] != legacy["snapshot_hash"]]
        (self.ws.state / "discovery-review-queue.json").write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, "snapshot_identity_mismatch"):
            self.q.next_items(self.ws, now=LATER)
        self.q.ingest(self.ws, [record()], now=LATER)
        repaired = self.q.next_items(self.ws, now=LATER)[0]
        self.assertEqual(repaired["posting_url"], record()["posting_url"])
        self.assertEqual(repaired["revision"], row["revision"])
        self.assertEqual(repaired["observations"][0], legacy)

    def test_identity_recovery_accepts_both_hash_versions_of_the_active_snapshot(self):
        first = record(requisition_id="shared-442")
        other = record(source_record_id="other-posting", requisition_id="shared-442",
                       posting_url="https://example.test/other", raw={"description": "Other posting duties."})
        state = self.q.ingest(self.ws, [first, other], now=NOW)
        original = copy.deepcopy(next(row for row in state["items"].values()
                                      if row["observations"][0]["source_record_id"] == "result-1"))
        legacy = copy.deepcopy(original["observations"][0])
        legacy["content_hash"] = "5787303dd0f3ad5a3475439e5d40bc4191f38e153b33235edc131351b898f2af"
        observations = [legacy, *[copy.deepcopy(o) for row in state["items"].values() for o in row["observations"]]]
        original.update(review_id="review:" + "d" * 64, observations=observations)
        state["items"] = {original["review_id"]: original}
        (self.ws.state / "discovery-review-queue.json").write_text(json.dumps(state))
        try:
            plan = self.q.plan_posting_identity_recovery(self.ws)
        except ValueError as exc:
            self.fail(f"Both valid content-hash versions must remain recoverable: {exc}")
        self.q.recover_posting_identities(self.ws, review_ids=plan["review_ids"],
            expected_queue_hash=plan["expected_queue_hash"], now=LATER)
        pending = self.q.next_items(self.ws, now=LATER)
        self.assertEqual({row["source_record_id"] for row in pending}, {"result-1", "other-posting"})
        self.assertCountEqual([o for row in self.q.load_queue(self.ws)["items"].values()
                              for o in row["observations"]], observations)

    def test_legacy_url_only_recovery_requires_exact_active_snapshot_to_avoid_guessing(self):
        for has_active_snapshot in (False, True):
            with self.subTest(has_active_snapshot=has_active_snapshot), tempfile.TemporaryDirectory() as folder:
                workspace = create_workspace(Path(folder))
                first = record(requisition_id="shared-442", posting_url="https://example.test/a")
                other = record(source_record_id="different-posting", requisition_id="shared-442",
                               posting_url="https://example.test/other", raw={"description": "Another role."})
                changed_url = {**first, "posting_url": "https://example.test/b"}
                for minute, item in enumerate((first, other, changed_url, first)):
                    queue = self.q.ingest(workspace, [item], now=f"2026-09-14T12:{minute:02}:00+00:00")
                rows = list(queue["items"].values())
                original = copy.deepcopy(next(row for row in rows if row["observations"][0]["source_record_id"] == "result-1"))
                original.pop("content_hash_version", None)
                if not has_active_snapshot:
                    original.pop("active_snapshot_hash", None)
                observations = [copy.deepcopy(o) for row in rows for o in row["observations"]]
                for observation in observations:
                    if observation["source_record_id"] == "result-1":
                        observation["content_hash"] = "5787303dd0f3ad5a3475439e5d40bc4191f38e153b33235edc131351b898f2af"
                    else:
                        observation["content_hash"] = "7013a4b65e17ef2c82e1e5e6a6b0f3554f3984c58250bde2c8ffdb2cd260aabe"
                original.update(review_id="review:" + "e" * 64, observations=observations,
                                content_hash="5787303dd0f3ad5a3475439e5d40bc4191f38e153b33235edc131351b898f2af")
                queue["items"] = {original["review_id"]: original}
                before_receipts = copy.deepcopy(queue["intake_batches"])
                (workspace.state / "discovery-review-queue.json").write_text(json.dumps(queue))
                plan = self.q.plan_posting_identity_recovery(workspace)
                self.q.recover_posting_identities(workspace, review_ids=plan["review_ids"],
                    expected_queue_hash=plan["expected_queue_hash"], now=LATER)
                recovered = self.q.load_queue(workspace)
                row = next(row for row in recovered["items"].values() if row["observations"][0]["source_record_id"] == "result-1")
                self.assertEqual(bool(row.get("snapshot_selection_required")), not has_active_snapshot)
                if has_active_snapshot:
                    pending = {row["source_record_id"]: row for row in self.q.next_items(workspace, now=LATER)}
                    self.assertEqual(pending["result-1"]["posting_url"], "https://example.test/a")
                else:
                    self.assertIn(row["review_id"], plan["splits"][0]["snapshot_selection_required"])
                    with self.assertRaisesRegex(ValueError, "posting_snapshot_selection_required"):
                        self.q.next_items(workspace, now=LATER)
                self.assertCountEqual([o for row in recovered["items"].values() for o in row["observations"]], observations)
                self.assertEqual(recovered["intake_batches"], before_receipts)

    def test_recovery_holds_unprovable_other_id_until_fresh_capture_not_historical_replay(self):
        original = self.alternating_legacy_queue(ambiguous_other=True)
        plan = self.q.plan_posting_identity_recovery(self.ws)
        self.q.recover_posting_identities(self.ws, review_ids=plan["review_ids"],
            expected_queue_hash=plan["expected_queue_hash"], now=LATER)
        queue = self.q.load_queue(self.ws)
        held = next(row for row in queue["items"].values() if row["observations"][0]["source_record_id"] == "different-posting")
        self.assertTrue(held.get("snapshot_selection_required"))
        with self.assertRaisesRegex(ValueError, "posting_snapshot_selection_required"):
            self.q.next_items(self.ws, now=LATER)
        with self.assertRaisesRegex(ValueError, "posting_snapshot_selection_required"):
            self.q.record_decision(self.ws, held["review_id"], decision("excluded"),
                expected_context=self.q.review_context(self.ws), expected_revision=held["revision"], now=LATER)
        other = record(source_record_id="different-posting", requisition_id="shared-442",
                       posting_url="https://example.test/other", raw={"description": "Another role."})
        self.q.ingest(self.ws, [other], now=NOW)
        self.assertTrue(self.q.load_queue(self.ws)["items"][held["review_id"]]["snapshot_selection_required"])
        fresh = "2026-09-16T12:00:00+00:00"
        self.q.ingest(self.ws, [other], now=fresh)
        resolved = self.q.load_queue(self.ws)["items"][held["review_id"]]
        self.assertFalse(resolved.get("snapshot_selection_required"))
        self.assertGreater(resolved["revision"], held["revision"])
        pending = {row["source_record_id"]: row for row in self.q.next_items(self.ws, now=fresh)}
        self.assertEqual(pending["different-posting"]["raw"]["description"], "Another role.")
        self.assertCountEqual([o for row in self.q.load_queue(self.ws)["items"].values()
                              for o in row["observations"]], original["observations"])

    def test_empty_historical_intake_cannot_cover_never_ingested_records(self):
        self.q.ingest(self.ws, [], now=NOW, source="indeed")
        with self.assertRaisesRegex(ValueError, "retrieval"):
            self.q.validate_delivery(self.ws, {"source_results": {"indeed": {
                "success": True, "completed_at": LATER, "seen_records": ["never-ingested"]}}}, now=LATER)

    def test_reassessment_must_be_delivered_again_to_refresh_canonical_assessment(self):
        row = next(iter(self.q.ingest(self.ws, [record()], now=NOW)["items"].values()))
        row = self.q.record_decision(self.ws, row["review_id"], decision("qualifying"), expected_context=self.q.review_context(self.ws), expected_revision=1, now=NOW)
        pending = self.q.next_items(self.ws, now=NOW)[0]
        self.q.mark_delivered(self.ws, pending, "JOB-000001")
        self.assertTrue(self.q.summary(self.ws, now=NOW)["review_complete"])
        (self.ws.profile / "Career_Profile.md").write_text("Revised approved evidence")
        row = self.q.record_decision(self.ws, row["review_id"], decision("qualifying"), expected_context=self.q.review_context(self.ws), expected_revision=row["revision"], now=LATER)
        self.assertNotIn("job_id", row)
        self.assertEqual(self.q.summary(self.ws, now=LATER)["ready_for_delivery"], 1)

    def test_profile_change_between_read_and_decision_rejects_stale_exclusion(self):
        self.q.ingest(self.ws, [record()], now=NOW)
        row = self.q.next_items(self.ws, now=NOW)[0]
        (self.ws.profile / "Career_Profile.md").write_text("New evidence changes the assessment basis")
        with self.assertRaisesRegex(ValueError, "stale_review_context"):
            self.q.record_decision(self.ws, row["review_id"], decision("excluded"),
                expected_revision=row["revision"], expected_context=row["expected_context"], now=LATER)
        self.assertEqual(self.q.summary(self.ws, now=LATER)["unreviewed"], 1)

    def test_combined_summary_cannot_mix_old_reviews_with_concurrent_new_intake(self):
        from tests.retrieval_fixtures import board_scope
        from career_pipeline.job_store import WorkspaceLockedError
        board_scope(self.ws, "greenhouse", [], NOW)
        original_load = self.q.load_queue
        attempted = False
        mutations = []

        def insert_between_summary_reads():
            try:
                self.q.ingest(self.ws, [record(source="greenhouse")], now=NOW)
                mutations.append("accepted")
            except WorkspaceLockedError:
                mutations.append("locked")

        def interleaving_load(workspace):
            nonlocal attempted
            result = original_load(workspace)
            if not attempted:
                attempted = True
                writer = threading.Thread(target=insert_between_summary_reads)
                writer.start()
                writer.join(timeout=2)
                self.assertFalse(writer.is_alive())
            return result

        with patch.object(self.q, "load_queue", side_effect=interleaving_load):
            report = self.q.summary(self.ws, now=NOW)
        self.assertFalse(report["complete"] and mutations == ["accepted"],
            "A new pending intake cannot coexist with a summary claiming all review and retrieval work is complete")


if __name__ == "__main__":
    unittest.main()
