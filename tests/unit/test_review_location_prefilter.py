from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from career_pipeline import criteria, review_queue
from career_pipeline.atomic import atomic_write_json
from career_pipeline.workspace import create_workspace
from tests.integration.test_discovery_delivery import install_criteria
from tests.unit.test_location_prefilter import location_scope
from tests.unit.test_review_queue import LATER, NOW, decision, record


def approve_location_scope(workspace, scope=None):
    base = install_criteria(workspace)
    scoped = replace(base, discovery_location_scope=scope or location_scope())
    atomic_write_json(workspace.profile / "Search_Criteria.json", criteria.criteria_to_mapping(scoped))
    criteria.approve_workspace_criteria(workspace,
        expected_readable_sha256=scoped.readable_criteria_sha256,
        expected_structured_sha256=scoped.structured_sha256)
    return scoped


class ReviewLocationPrefilterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = create_workspace(Path(self.temp.name))

    def test_intake_excludes_only_proven_nonlocal_rows_and_keeps_all_receipts(self):
        approve_location_scope(self.ws)
        queue = review_queue.ingest(self.ws, [record(1, location="Costa Mesa, California"),
            record(2, location="Remote US"), record(3, location="United States"),
            record(4, location="Bethesda, MD"), record(5, location="")], now=NOW)
        self.assertEqual(len(queue["items"]), 5)
        excluded = [r for r in queue["items"].values() if r["status"] == "excluded"]
        self.assertEqual(len(excluded), 1)
        row = excluded[0]
        self.assertEqual(row["decision"]["reason_code"], "nonlocal_without_remote_option")
        proof = row["decision"]["prefilter"]
        self.assertEqual(proof["snapshot_hash"], row["observations"][0]["snapshot_hash"])
        self.assertEqual(proof["reviewed_revision"], 1)
        self.assertEqual(proof["expected_context"], row["approval_fingerprint"])
        self.assertEqual(row["revision"], 2)
        self.assertEqual(len(review_queue.next_items(self.ws, now=NOW)), 4)
        self.assertEqual(next(iter(queue["intake_batches"].values()))["source_record_ids"],
                         ["result-1", "result-2", "result-3", "result-4", "result-5"])
        self.assertEqual(len(list((self.ws.sources / "discovery-review").glob("*.json"))), 5)

    def test_country_only_compounds_survive_intake_with_receipts_and_full_descriptions(self):
        approve_location_scope(self.ws)
        records = [record(1, location="United States (US)"),
                   record(2, location="USA, United States"), record(3, location="Seattle, US")]
        queue = review_queue.ingest(self.ws, records, now=NOW)
        self.assertEqual({row["location"]: row["status"] for row in queue["items"].values()}, {
            "United States (US)": "unreviewed", "USA, United States": "unreviewed", "Seattle, US": "excluded"})
        pending = review_queue.next_items(self.ws, now=NOW)
        self.assertEqual({row["source_record_id"] for row in pending}, {"result-1", "result-2"})
        self.assertTrue(all(row["raw"]["description"] == records[0]["raw"]["description"] for row in pending))
        self.assertEqual(next(iter(queue["intake_batches"].values()))["source_record_ids"],
                         ["result-1", "result-2", "result-3"])
        self.assertEqual(len(list((self.ws.sources / "discovery-review").glob("*.json"))), 3)

    def test_version_one_country_exclusions_reopen_through_normal_prefilter(self):
        approve_location_scope(self.ws)
        queue = review_queue.ingest(self.ws, [record(1, location="United States (US)"),
                                             record(2, location="USA, United States")], now=NOW)
        historical = {}
        for row in queue["items"].values():
            prior = decision("excluded", reason_code="nonlocal_without_remote_option", prefilter={
                "policy": "exclude_nonlocal_without_remote_option", "matcher_version": 1,
                "snapshot_hash": row["observations"][0]["snapshot_hash"],
                "reviewed_revision": row["revision"], "expected_context": review_queue.review_context(self.ws),
            })
            historical[row["review_id"]] = review_queue.record_decision(self.ws, row["review_id"], prior,
                expected_revision=row["revision"], expected_context=review_queue.review_context(self.ws), now=NOW)
        before = review_queue.load_queue(self.ws)
        self.assertEqual(review_queue.summary(self.ws, now=LATER)["unreviewed"], 2)
        preview = review_queue.apply_location_prefilter(self.ws, now=LATER, dry_run=True)
        self.assertEqual(preview["would_reopen"], 2)
        self.assertEqual(review_queue.load_queue(self.ws), before)
        applied = review_queue.apply_location_prefilter(self.ws, now=LATER)
        self.assertEqual(applied["reopened"], 2)
        self.assertEqual(applied["excluded"], 0)
        current = review_queue.load_queue(self.ws)
        for key, row in current["items"].items():
            self.assertEqual(row["status"], "unreviewed")
            self.assertIsNone(row["decision"])
            self.assertEqual(row["history"][-1]["decision"], historical[key]["decision"])
            self.assertEqual(row["observations"], historical[key]["observations"])
        self.assertEqual(current["intake_batches"], before["intake_batches"])
        self.assertEqual(review_queue.apply_location_prefilter(self.ws, now=LATER)["reopened"], 0)

    def test_cli_preview_is_read_only_and_apply_replays_without_revising_decisions(self):
        review_queue.ingest(self.ws, [record(1, location="Costa Mesa, California"), record(2)], now=NOW)
        approve_location_scope(self.ws)
        path = self.ws.state / "discovery-review-queue.json"
        before = path.read_bytes()
        script = Path(__file__).resolve().parents[2] / "scripts/review_discovery_queue.py"
        preview = subprocess.run([sys.executable, str(script), "--workspace", str(self.ws.root),
            "--occurred-at", LATER, "prefilter", "--dry-run"], capture_output=True, text=True)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(json.loads(preview.stdout)["would_exclude"], 1)
        self.assertEqual(path.read_bytes(), before)
        applied = review_queue.apply_location_prefilter(self.ws, now=LATER)
        self.assertEqual(applied["excluded"], 1)
        after = path.read_bytes()
        replayed = review_queue.apply_location_prefilter(self.ws, now=LATER)
        self.assertEqual(replayed["excluded"], 0)
        self.assertEqual(path.read_bytes(), after)

    def test_changed_criteria_clears_stale_auto_exclusion_but_preserves_its_proof(self):
        approve_location_scope(self.ws)
        queue = review_queue.ingest(self.ws, [record(location="Costa Mesa, California")], now=NOW)
        old = next(iter(queue["items"].values()))
        self.assertEqual(old["status"], "excluded")
        approve_location_scope(self.ws, replace(location_scope(), exception_labels=("Costa Mesa",)))
        report = review_queue.apply_location_prefilter(self.ws, now=LATER)
        self.assertEqual(report["excluded"], 0)
        self.assertEqual(report["reopened"], 1)
        current = review_queue.load_queue(self.ws)["items"][old["review_id"]]
        self.assertEqual(current["status"], "unreviewed")
        self.assertIsNone(current["decision"])
        self.assertEqual(current["history"][-1]["decision"], old["decision"])
        self.assertEqual(current["revision"], old["revision"] + 1)
        self.assertEqual(review_queue.next_items(self.ws, now=LATER)[0]["status"], "unreviewed")

    def test_outdated_matcher_reopens_automatic_exclusion_before_batch_reassessment(self):
        approve_location_scope(self.ws)
        queue = review_queue.ingest(self.ws, [record(location="Costa Mesa, California")], now=NOW)
        row = next(iter(queue["items"].values()))
        row["decision"]["prefilter"]["matcher_version"] = -1
        atomic_write_json(self.ws.state / "discovery-review-queue.json", queue)
        self.assertEqual(review_queue.summary(self.ws, now=LATER)["unreviewed"], 1)
        old_decision = json.loads(json.dumps(row["decision"]))
        report = review_queue.apply_location_prefilter(self.ws, now=LATER)
        self.assertEqual(report["excluded"], 1)
        current = review_queue.load_queue(self.ws)["items"][row["review_id"]]
        self.assertEqual(current["status"], "excluded")
        self.assertEqual(current["history"][-1]["decision"], old_decision)
        self.assertNotEqual(current["decision"]["prefilter"]["matcher_version"], -1)

    def test_changed_context_keeps_manual_decision_for_explicit_reassessment(self):
        queue = review_queue.ingest(self.ws, [record(location="Costa Mesa, California")], now=NOW)
        row = next(iter(queue["items"].values()))
        decided = review_queue.record_decision(self.ws, row["review_id"], decision("excluded"),
            expected_context=review_queue.review_context(self.ws), expected_revision=1, now=NOW)
        approve_location_scope(self.ws)
        report = review_queue.apply_location_prefilter(self.ws, now=LATER)
        self.assertEqual(report["excluded"], 0)
        self.assertEqual(report["reopened"], 0)
        self.assertEqual(review_queue.load_queue(self.ws)["items"][row["review_id"]], decided)
        self.assertEqual(review_queue.next_items(self.ws, now=LATER)[0]["status"], "unreviewed")

    def test_batch_keeps_current_user_decisions_and_corrupted_snapshots_for_review(self):
        queue = review_queue.ingest(self.ws, [record(1, location="Costa Mesa, California"),
                                             record(2, location="Seattle, Washington")], now=NOW)
        approve_location_scope(self.ws)
        rows = list(queue["items"].values())
        chosen = rows[0]
        decided = review_queue.record_decision(self.ws, chosen["review_id"], decision("qualifying"),
            expected_context=review_queue.review_context(self.ws), expected_revision=1, now=LATER)
        bad_snapshot = self.ws.root / rows[1]["observations"][0]["snapshot"]
        bad_snapshot.write_text("{}")
        report = review_queue.apply_location_prefilter(self.ws, now=LATER)
        self.assertEqual(report["excluded"], 0)
        self.assertEqual(report["held"]["snapshot_invalid"], 1)
        self.assertEqual(review_queue.load_queue(self.ws)["items"][chosen["review_id"]], decided)

    def test_criteria_drift_during_batch_cannot_write_an_exclusion_from_old_policy(self):
        from career_pipeline import location_prefilter
        review_queue.ingest(self.ws, [record(location="Costa Mesa, California")], now=NOW)
        approve_location_scope(self.ws)
        original = location_prefilter.exclusion_decision
        before = (self.ws.state / "discovery-review-queue.json").read_bytes()

        def edit_profile_during_classification(record, scope):
            result = original(record, scope)
            (self.ws.profile / "Career_Profile.md").write_text("Changed approval context during classification")
            return result

        with patch.object(location_prefilter, "exclusion_decision", side_effect=edit_profile_during_classification):
            with self.assertRaisesRegex(ValueError, "stale_review_context"):
                review_queue.apply_location_prefilter(self.ws, now=LATER)
        self.assertEqual((self.ws.state / "discovery-review-queue.json").read_bytes(), before)

    def test_unapproved_scope_does_not_prevent_lossless_intake_or_apply_an_exclusion(self):
        approve_location_scope(self.ws)
        (self.ws.state / "search-criteria-approval.json").write_text("{}")
        queue = review_queue.ingest(self.ws, [record(location="Costa Mesa, California")], now=NOW)
        self.assertEqual(next(iter(queue["items"].values()))["status"], "unreviewed")
        self.assertEqual(len(queue["intake_batches"]), 1)
        with self.assertRaises(criteria.CriteriaError):
            review_queue.apply_location_prefilter(self.ws, now=LATER)

    def test_mixed_posting_ids_are_held_for_identity_recovery_before_geographic_exclusion(self):
        queue = review_queue.ingest(self.ws, [record(1, location="Costa Mesa, California"),
            record(2, location="Seattle, Washington")], now=NOW)
        rows = list(queue["items"].values())
        row = rows[0]
        row["observations"].extend(rows[1]["observations"])
        queue["items"] = {row["review_id"]: row}
        path = self.ws.state / "discovery-review-queue.json"
        path.write_text(json.dumps(queue))
        approve_location_scope(self.ws)
        before = path.read_bytes()
        report = review_queue.apply_location_prefilter(self.ws, now=LATER)
        self.assertEqual(report["held"]["mixed_posting_ids"], 1)
        self.assertEqual(report["excluded"], 0)
        self.assertEqual(path.read_bytes(), before)

    def test_intake_context_drift_retains_all_records_before_safe_replay(self):
        from career_pipeline import location_prefilter
        approve_location_scope(self.ws)
        original = location_prefilter.exclusion_decision

        def edit_profile_during_classification(record, scope):
            result = original(record, scope)
            (self.ws.profile / "Career_Profile.md").write_text("Changed approval context during intake")
            return result

        with patch.object(location_prefilter, "exclusion_decision", side_effect=edit_profile_during_classification):
            with self.assertRaisesRegex(ValueError, "stale_review_context"):
                review_queue.ingest(self.ws, [record(1, location="Costa Mesa, California"),
                    record(2, location="Seattle, Washington")], now=NOW)
        queue = review_queue.load_queue(self.ws)
        self.assertEqual(len(queue["items"]), 2)
        self.assertEqual({row["status"] for row in queue["items"].values()}, {"unreviewed"})
        self.assertEqual(len(queue["intake_batches"]), 1)
        replayed = review_queue.apply_location_prefilter(self.ws, now=LATER)
        self.assertEqual(replayed["excluded"], 2)

    def test_geographic_exclusions_preserve_original_retrieval_receipts(self):
        from tests.retrieval_fixtures import board_scope
        from career_pipeline import retrieval
        approve_location_scope(self.ws)
        scope = board_scope(self.ws, "greenhouse", [{"id": "outside-scope", "title": "Operations Lead",
            "absolute_url": "https://example.test/jobs/a", "location": {"name": "Costa Mesa, California"},
            "content": "Lead operations and customer workflows."}], NOW)
        self.assertEqual(review_queue.summary(self.ws, now=NOW)["excluded"], 1)
        self.assertTrue(retrieval.summary(self.ws, now=NOW)["complete"])
        review_queue.validate_delivery(self.ws, {"source_results": {"greenhouse": {
            "success": True, "completed_at": NOW, "seen_records": ["outside-scope"],
            "intake_ids": scope["intake_ids"], "coverage_scope_ids": [scope["scope_id"]]}}}, now=NOW)


if __name__ == "__main__":
    unittest.main()
