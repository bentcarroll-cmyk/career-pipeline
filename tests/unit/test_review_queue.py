from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
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
        self.assertTrue(self.q.summary(self.ws, now=NOW)["complete"])

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

    def test_actual_empty_intake_can_complete_but_missing_intake_cannot(self):
        payload = {"source_results": {"indeed": {"success": True}}}
        with self.assertRaisesRegex(ValueError, "review_queue_incomplete"):
            self.q.validate_delivery(self.ws, payload, now=NOW)
        self.q.ingest(self.ws, [], now=NOW, source="indeed")
        payload["source_results"]["indeed"].update(intake_ids=list(self.q.load_queue(self.ws)["intake_batches"]), completed_at=NOW)
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
        ws = approved_workspace(self.ws.root)
        item = reviewed(1)
        intake = {**asdict(item.candidate), "raw": {"description": item.posting_markdown}}
        row = next(iter(self.q.ingest(ws, [intake], now=NOW)["items"].values()))
        self.q.record_decision(ws, row["review_id"], decision("qualifying"), expected_context=self.q.review_context(self.ws), expected_revision=row["revision"], now=NOW)
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
            tuple(self.q.load_queue(ws)["intake_batches"]))),))
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

    def test_empty_historical_intake_cannot_cover_never_ingested_records(self):
        self.q.ingest(self.ws, [], now=NOW, source="indeed")
        with self.assertRaisesRegex(ValueError, "review_intake"):
            self.q.validate_delivery(self.ws, {"source_results": {"indeed": {
                "success": True, "completed_at": LATER, "seen_records": ["never-ingested"]}}}, now=LATER)

    def test_reassessment_must_be_delivered_again_to_refresh_canonical_assessment(self):
        row = next(iter(self.q.ingest(self.ws, [record()], now=NOW)["items"].values()))
        row = self.q.record_decision(self.ws, row["review_id"], decision("qualifying"), expected_context=self.q.review_context(self.ws), expected_revision=1, now=NOW)
        pending = self.q.next_items(self.ws, now=NOW)[0]
        self.q.mark_delivered(self.ws, pending, "JOB-000001")
        self.assertTrue(self.q.summary(self.ws, now=NOW)["complete"])
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


if __name__ == "__main__":
    unittest.main()
