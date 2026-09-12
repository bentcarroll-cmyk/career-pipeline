import json
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from career_pipeline.automation_policy import render_automation
from career_pipeline.job_store import (
    create_job,
    read_job,
    reverify_job,
    update_job_status,
    workspace_lock,
)
from career_pipeline.reconciliation import (
    LifecycleDecision,
    LifecycleEvidence,
    LifecycleReconciliationError,
    evidence_receipt_hash,
    minimal_receipt,
    reconcile_lifecycle_evidence,
)
from career_pipeline.workspace import create_workspace
from tests.unit.test_job_store import synthetic_assessment, synthetic_candidate


class LifecycleAutomationTests(unittest.TestCase):
    def test_reverification_does_not_advance_status_decision_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = create_job(
                workspace,
                synthetic_candidate(),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T22:00:00Z",
            )["job_id"]
            update_job_status(
                workspace,
                job_id,
                "applied",
                occurred_at="2026-09-11T22:01:00Z",
            )
            reverify_job(
                workspace,
                job_id,
                replace(
                    synthetic_candidate(),
                    verified_at="2026-09-11T22:10:00Z",
                    raw_field_hash="b" * 64,
                ),
                synthetic_assessment(),
                posting_markdown="# Updated synthetic posting\n",
                assessment_markdown="# Updated synthetic assessment\n",
                occurred_at="2026-09-11T22:10:00Z",
            )

            result = reconcile_lifecycle_evidence(
                workspace,
                LifecycleEvidence(
                    "google-calendar",
                    "synthetic-interview-before-reverification",
                    "2026-09-11T22:05:00Z",
                    "Example Cooperative",
                    "Director of Operations",
                    "SYN-601",
                    "interview_invitation",
                ),
                enabled_sources=("google-calendar",),
            )

            self.assertEqual(result.decision.action, "apply_update")
            self.assertEqual(read_job(workspace, job_id)["status"], "interviewing")

    def test_same_target_observation_protects_against_older_conflicting_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = create_job(
                workspace,
                synthetic_candidate(),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T22:00:00Z",
            )["job_id"]
            update_job_status(
                workspace,
                job_id,
                "applied",
                occurred_at="2026-09-11T22:01:00Z",
            )
            confirmation = reconcile_lifecycle_evidence(
                workspace,
                LifecycleEvidence(
                    "gmail",
                    "synthetic-newer-same-target-confirmation",
                    "2026-09-11T22:10:00Z",
                    "Example Cooperative",
                    "Director of Operations",
                    "SYN-601",
                    "application_confirmation",
                ),
                enabled_sources=("gmail",),
            )
            rejection = reconcile_lifecycle_evidence(
                workspace,
                LifecycleEvidence(
                    "gmail",
                    "synthetic-older-conflicting-rejection",
                    "2026-09-11T22:05:00Z",
                    "Example Cooperative",
                    "Director of Operations",
                    "SYN-601",
                    "rejection",
                ),
                enabled_sources=("gmail",),
            )

            self.assertEqual(confirmation.decision.action, "apply_update")
            self.assertEqual(rejection.decision.action, "needs_review")
            self.assertEqual(
                rejection.decision.reason,
                "canonical_status_newer_than_evidence",
            )
            self.assertEqual(read_job(workspace, job_id)["status"], "applied")
            events = [
                json.loads(line)
                for line in (
                    workspace.jobs / job_id / "events.jsonl"
                ).read_text().splitlines()
            ]
            observations = [
                event
                for event in events
                if event["event_type"] == "lifecycle_status_observed"
            ]
            self.assertEqual(len(observations), 1)
            self.assertEqual(observations[0]["status"], "applied")

    def test_same_target_observation_recovers_after_receipt_crash(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = create_job(
                workspace,
                synthetic_candidate(),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T22:00:00Z",
            )["job_id"]
            update_job_status(
                workspace,
                job_id,
                "applied",
                occurred_at="2026-09-11T22:01:00Z",
            )
            evidence = LifecycleEvidence(
                "gmail",
                "synthetic-same-target-receipt-crash",
                "2026-09-11T22:10:00Z",
                "Example Cooperative",
                "Director of Operations",
                "SYN-601",
                "application_confirmation",
            )

            with patch(
                "career_pipeline.reconciliation.atomic_write_json",
                side_effect=OSError("synthetic same-target receipt interruption"),
            ):
                with self.assertRaises(OSError):
                    reconcile_lifecycle_evidence(
                        workspace,
                        evidence,
                        enabled_sources=("gmail",),
                    )
            update_job_status(
                workspace,
                job_id,
                "not_pursuing",
                occurred_at="2026-09-11T22:20:00Z",
                metadata={"reason_code": "synthetic_user_decision"},
            )

            replay = reconcile_lifecycle_evidence(
                workspace,
                evidence,
                enabled_sources=("gmail",),
            )

            self.assertEqual(replay.decision.action, "apply_update")
            self.assertEqual(replay.decision.target_status, "applied")
            self.assertEqual(read_job(workspace, job_id)["status"], "not_pursuing")
            receipt = json.loads(replay.receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["observed_at"], "2026-09-11T22:10:00Z")
            events = [
                json.loads(line)
                for line in (
                    workspace.jobs / job_id / "events.jsonl"
                ).read_text().splitlines()
            ]
            matching = [
                event
                for event in events
                if event.get("metadata", {}).get("source_receipt_hash")
                == evidence_receipt_hash(evidence)
            ]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["event_type"], "lifecycle_status_observed")

    def test_semantically_contradictory_receipts_fail_before_dedup(self) -> None:
        cases = {
            "wrong_target": {"target_status": "closed"},
            "unsupported_event": {"event_class": "newsletter"},
            "apply_review_reason": {
                "reason": "status_transition_requires_review"
            },
            "invalid_observed_at": {"observed_at": "not-a-time"},
            "review_with_apply_reason": {
                "action": "needs_review",
                "reason": "exact_unambiguous_evidence",
            },
            "matched_review_reason_labeled_ignore": {
                "action": "ignore",
                "reason": "status_transition_requires_review",
            },
            "unmatched_review_reason_labeled_ignore": {
                "action": "ignore",
                "job_id": None,
                "target_status": None,
                "reason": "exact_role_match_required",
            },
        }
        for case, changes in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as raw:
                workspace = create_workspace(Path(raw) / "Synthetic-Career")
                job_id = create_job(
                    workspace,
                    synthetic_candidate(),
                    synthetic_assessment(),
                    posting_markdown="# Synthetic posting\n",
                    assessment_markdown="# Synthetic assessment\n",
                    occurred_at="2026-09-11T22:00:00Z",
                )["job_id"]
                evidence = LifecycleEvidence(
                    "gmail",
                    f"synthetic-semantic-receipt-{case}",
                    "2026-09-11T22:05:00Z",
                    "Example Cooperative",
                    "Director of Operations",
                    "SYN-601",
                    "application_confirmation",
                )
                receipt_hash = evidence_receipt_hash(evidence)
                receipt_path = (
                    workspace.runs
                    / "lifecycle"
                    / f"receipt-{receipt_hash[:20]}.json"
                )
                receipt = minimal_receipt(
                    evidence,
                    LifecycleDecision(
                        "apply_update",
                        job_id=job_id,
                        target_status="applied",
                        reason="exact_unambiguous_evidence",
                    ),
                )
                receipt.update(changes)
                receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
                before = receipt_path.read_bytes()

                with self.assertRaises(LifecycleReconciliationError):
                    reconcile_lifecycle_evidence(
                        workspace,
                        evidence,
                        enabled_sources=("gmail",),
                    )

                self.assertEqual(read_job(workspace, job_id)["status"], "new")
                self.assertEqual(receipt_path.read_bytes(), before)

    def test_legacy_nonactionable_ignore_receipt_does_not_block_later_evidence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = create_job(
                workspace,
                synthetic_candidate(),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T22:00:00Z",
            )["job_id"]
            legacy_evidence = LifecycleEvidence(
                "gmail",
                "synthetic-legacy-newsletter",
                "2026-09-11T22:01:00Z",
                "Example Cooperative",
                "Director of Operations",
                "SYN-601",
                "newsletter",
            )
            legacy_receipt = minimal_receipt(
                legacy_evidence,
                LifecycleDecision(
                    "ignore",
                    reason="event_class_not_actionable",
                ),
            )
            legacy_hash = evidence_receipt_hash(legacy_evidence)
            legacy_path = (
                workspace.runs
                / "lifecycle"
                / f"receipt-{legacy_hash[:20]}.json"
            )
            legacy_path.write_text(json.dumps(legacy_receipt), encoding="utf-8")
            before = legacy_path.read_bytes()

            result = reconcile_lifecycle_evidence(
                workspace,
                LifecycleEvidence(
                    "gmail",
                    "synthetic-valid-after-legacy-ignore",
                    "2026-09-11T22:05:00Z",
                    "Example Cooperative",
                    "Director of Operations",
                    "SYN-601",
                    "application_confirmation",
                ),
                enabled_sources=("gmail",),
            )

            self.assertEqual(result.decision.action, "apply_update")
            self.assertEqual(read_job(workspace, job_id)["status"], "applied")
            self.assertEqual(legacy_path.read_bytes(), before)

    def test_stale_evidence_preserves_newer_nonterminal_canonical_decision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = create_job(
                workspace,
                synthetic_candidate(),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T22:00:00Z",
            )["job_id"]
            update_job_status(
                workspace,
                job_id,
                "interviewing",
                occurred_at="2026-09-11T22:10:00Z",
                metadata={"reason_code": "synthetic_user_confirmed_interview"},
            )

            result = reconcile_lifecycle_evidence(
                workspace,
                LifecycleEvidence(
                    "gmail",
                    "synthetic-stale-rejection",
                    "2026-09-11T22:05:00Z",
                    "Example Cooperative",
                    "Director of Operations",
                    "SYN-601",
                    "rejection",
                ),
                enabled_sources=("gmail",),
            )

            self.assertEqual(result.decision.action, "needs_review")
            self.assertEqual(
                result.decision.reason,
                "canonical_status_newer_than_evidence",
            )
            self.assertEqual(read_job(workspace, job_id)["status"], "interviewing")
            receipt = json.loads(result.receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["action"], "needs_review")

    def test_replay_recovers_committed_decision_after_receipt_write_crash(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = create_job(
                workspace,
                synthetic_candidate(),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T22:00:00Z",
            )["job_id"]
            evidence = LifecycleEvidence(
                "gmail",
                "synthetic-receipt-write-crash",
                "2026-09-11T22:05:00Z",
                "Example Cooperative",
                "Director of Operations",
                "SYN-601",
                "application_confirmation",
            )

            with patch(
                "career_pipeline.reconciliation.atomic_write_json",
                side_effect=OSError("synthetic receipt interruption"),
            ):
                with self.assertRaises(OSError):
                    reconcile_lifecycle_evidence(
                        workspace,
                        evidence,
                        enabled_sources=("gmail",),
                    )
            self.assertEqual(read_job(workspace, job_id)["status"], "applied")

            update_job_status(
                workspace,
                job_id,
                "not_pursuing",
                occurred_at="2026-09-11T22:10:00Z",
                metadata={"reason_code": "synthetic_user_decision"},
            )
            replay = reconcile_lifecycle_evidence(
                workspace,
                evidence,
                enabled_sources=("gmail",),
            )

            self.assertEqual(replay.decision.action, "apply_update")
            self.assertEqual(replay.decision.target_status, "applied")
            self.assertEqual(
                replay.decision.reason,
                "exact_unambiguous_evidence",
            )
            self.assertEqual(read_job(workspace, job_id)["status"], "not_pursuing")
            receipt = json.loads(replay.receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["action"], "apply_update")
            self.assertEqual(receipt["target_status"], "applied")
            self.assertEqual(receipt["observed_at"], "2026-09-11T22:05:00Z")
            matching_events = [
                json.loads(line)
                for line in (
                    workspace.jobs / job_id / "events.jsonl"
                ).read_text().splitlines()
                if json.loads(line).get("metadata", {}).get(
                    "source_receipt_hash"
                )
                == evidence_receipt_hash(evidence)
            ]
            self.assertEqual(len(matching_events), 1)

    def test_malformed_incomplete_and_conflicting_receipts_fail_closed(self) -> None:
        cases = ("malformed", "non_object", "incomplete", "conflicting_hash")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as raw:
                workspace = create_workspace(Path(raw) / "Synthetic-Career")
                job_id = create_job(
                    workspace,
                    synthetic_candidate(),
                    synthetic_assessment(),
                    posting_markdown="# Synthetic posting\n",
                    assessment_markdown="# Synthetic assessment\n",
                    occurred_at="2026-09-11T22:00:00Z",
                )["job_id"]
                evidence = LifecycleEvidence(
                    "gmail",
                    f"synthetic-corrupt-receipt-{case}",
                    "2026-09-11T22:05:00Z",
                    "Example Cooperative",
                    "Director of Operations",
                    "SYN-601",
                    "application_confirmation",
                )
                receipt_hash = evidence_receipt_hash(evidence)
                receipt_path = (
                    workspace.runs
                    / "lifecycle"
                    / f"receipt-{receipt_hash[:20]}.json"
                )
                private_marker = "synthetic-private-receipt-content"
                if case == "malformed":
                    receipt_path.write_text(
                        '{"private": "' + private_marker + '",',
                        encoding="utf-8",
                    )
                elif case == "non_object":
                    receipt_path.write_text(
                        json.dumps([private_marker]),
                        encoding="utf-8",
                    )
                elif case == "incomplete":
                    receipt_path.write_text(
                        json.dumps({"source_receipt_hash": receipt_hash}),
                        encoding="utf-8",
                    )
                else:
                    value = minimal_receipt(
                        evidence,
                        LifecycleDecision(
                            "apply_update",
                            job_id=job_id,
                            target_status="applied",
                            reason="exact_unambiguous_evidence",
                        ),
                    )
                    suffix = "0" * 44
                    if receipt_hash.endswith(suffix):
                        suffix = "1" * 44
                    value["source_receipt_hash"] = receipt_hash[:20] + suffix
                    receipt_path.write_text(json.dumps(value), encoding="utf-8")
                before = receipt_path.read_bytes()

                with self.assertRaises(LifecycleReconciliationError) as raised:
                    reconcile_lifecycle_evidence(
                        workspace,
                        evidence,
                        enabled_sources=("gmail",),
                    )

                self.assertNotIn(private_marker, str(raised.exception))
                self.assertEqual(read_job(workspace, job_id)["status"], "new")
                self.assertEqual(receipt_path.read_bytes(), before)
                events = (
                    workspace.jobs / job_id / "events.jsonl"
                ).read_text().splitlines()
                self.assertEqual(len(events), 1)

    def test_commit_rechecks_status_after_concurrent_user_decision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = create_job(
                workspace,
                synthetic_candidate(),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T22:00:00Z",
            )["job_id"]
            evidence = LifecycleEvidence(
                "gmail",
                "synthetic-message-concurrent-user",
                "2026-09-11T22:05:00Z",
                "Example Cooperative",
                "Director of Operations",
                "SYN-601",
                "application_confirmation",
            )
            injected = False

            @contextmanager
            def lock_after_user_decision(value):
                nonlocal injected
                if not injected:
                    injected = True
                    update_job_status(
                        workspace,
                        job_id,
                        "not_pursuing",
                        occurred_at="2026-09-11T22:06:00Z",
                        metadata={"reason_code": "synthetic_user_decision"},
                    )
                with workspace_lock(value):
                    yield

            with patch(
                "career_pipeline.reconciliation.workspace_lock",
                new=lock_after_user_decision,
            ):
                result = reconcile_lifecycle_evidence(
                    workspace,
                    evidence,
                    enabled_sources=("gmail",),
                )

            self.assertEqual(result.decision.action, "needs_review")
            self.assertEqual(
                result.decision.reason,
                "status_transition_requires_review",
            )
            self.assertEqual(read_job(workspace, job_id)["status"], "not_pursuing")
            receipt = json.loads(result.receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["action"], "needs_review")
            self.assertEqual(receipt["reason"], "status_transition_requires_review")
            events = (workspace.jobs / job_id / "events.jsonl").read_text().splitlines()
            self.assertEqual(
                [json.loads(line)["status"] for line in events],
                ["new", "not_pursuing"],
            )

    def test_concurrent_same_evidence_returns_deduplicated_committed_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = create_job(
                workspace,
                synthetic_candidate(),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T22:00:00Z",
            )["job_id"]
            evidence = LifecycleEvidence(
                "gmail",
                "synthetic-message-concurrent-same",
                "2026-09-11T22:05:00Z",
                "Example Cooperative",
                "Director of Operations",
                "SYN-601",
                "application_confirmation",
            )
            injected = False
            inner = None

            @contextmanager
            def lock_after_same_evidence(value):
                nonlocal injected, inner
                if not injected:
                    injected = True
                    inner = reconcile_lifecycle_evidence(
                        workspace,
                        evidence,
                        enabled_sources=("gmail",),
                    )
                with workspace_lock(value):
                    yield

            with patch(
                "career_pipeline.reconciliation.workspace_lock",
                new=lock_after_same_evidence,
            ):
                outer = reconcile_lifecycle_evidence(
                    workspace,
                    evidence,
                    enabled_sources=("gmail",),
                )

            self.assertIsNotNone(inner)
            self.assertEqual(inner.decision.action, "apply_update")
            self.assertEqual(outer.decision.action, "ignore")
            self.assertEqual(outer.decision.reason, "evidence_already_seen")
            self.assertEqual(outer.receipt_path, inner.receipt_path)
            receipts = list((workspace.runs / "lifecycle").glob("receipt-*.json"))
            self.assertEqual(len(receipts), 1)
            events = (workspace.jobs / job_id / "events.jsonl").read_text().splitlines()
            self.assertEqual(len(events), 2)

    def test_concurrent_different_evidence_receipts_match_committed_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = create_job(
                workspace,
                synthetic_candidate(),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T22:00:00Z",
            )["job_id"]
            confirmation = LifecycleEvidence(
                "gmail",
                "synthetic-message-concurrent-confirmation",
                "2026-09-11T22:05:00Z",
                "Example Cooperative",
                "Director of Operations",
                "SYN-601",
                "application_confirmation",
            )
            rejection = LifecycleEvidence(
                "gmail",
                "synthetic-message-concurrent-rejection",
                "2026-09-11T22:06:00Z",
                "Example Cooperative",
                "Director of Operations",
                "SYN-601",
                "rejection",
            )
            injected = False
            inner = None

            @contextmanager
            def lock_after_rejection(value):
                nonlocal injected, inner
                if not injected:
                    injected = True
                    inner = reconcile_lifecycle_evidence(
                        workspace,
                        rejection,
                        enabled_sources=("gmail",),
                    )
                with workspace_lock(value):
                    yield

            with patch(
                "career_pipeline.reconciliation.workspace_lock",
                new=lock_after_rejection,
            ):
                outer = reconcile_lifecycle_evidence(
                    workspace,
                    confirmation,
                    enabled_sources=("gmail",),
                )

            self.assertIsNotNone(inner)
            self.assertEqual(inner.decision.action, "apply_update")
            self.assertEqual(outer.decision.action, "needs_review")
            self.assertEqual(read_job(workspace, job_id)["status"], "closed")
            outer_receipt = json.loads(outer.receipt_path.read_text(encoding="utf-8"))
            inner_receipt = json.loads(inner.receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(inner_receipt["action"], "apply_update")
            self.assertEqual(inner_receipt["target_status"], "closed")
            self.assertEqual(outer_receipt["action"], "needs_review")
            self.assertEqual(outer_receipt["target_status"], "applied")
            self.assertEqual(
                outer_receipt["reason"],
                "status_transition_requires_review",
            )

    def test_prompt_is_read_only_outside_verified_local_status(self) -> None:
        prompt = render_automation(
            "lifecycle",
            {
                "workspace_config": "State/config.json",
                "timezone": "America/New_York",
            },
        )
        self.assertIn("Never send", prompt)
        self.assertIn("minimal receipt", prompt)
        self.assertIn("canonical local job status", prompt)
        self.assertNotIn("Linear", prompt)

    def test_exact_evidence_updates_canonical_status_once_and_keeps_minimum(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = create_job(
                workspace,
                synthetic_candidate(),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T22:00:00Z",
            )["job_id"]
            evidence = LifecycleEvidence(
                source_kind="gmail",
                opaque_id="synthetic-message-4",
                observed_at="2026-09-11T22:05:00Z",
                employer="Example Cooperative",
                role_title="Director of Operations",
                requisition_id="SYN-601",
                event_class="application_confirmation",
            )

            first = reconcile_lifecycle_evidence(
                workspace,
                evidence,
                enabled_sources=("gmail",),
            )
            second = reconcile_lifecycle_evidence(
                workspace,
                evidence,
                enabled_sources=("gmail",),
            )

            self.assertEqual(first.decision.action, "apply_update")
            self.assertEqual(second.decision.action, "ignore")
            self.assertEqual(read_job(workspace, job_id)["status"], "applied")
            receipt = json.loads(first.receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["job_id"], job_id)
            self.assertEqual(
                set(receipt),
                {
                    "source_kind",
                    "source_receipt_hash",
                    "observed_at",
                    "event_class",
                    "action",
                    "job_id",
                    "target_status",
                    "reason",
                },
            )
            events = (workspace.jobs / job_id / "events.jsonl").read_text().splitlines()
            self.assertEqual(len(events), 2)

    def test_ambiguous_evidence_writes_receipt_without_status_change(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = create_job(
                workspace,
                synthetic_candidate(),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T22:00:00Z",
            )["job_id"]
            result = reconcile_lifecycle_evidence(
                workspace,
                LifecycleEvidence(
                    "google-calendar",
                    "synthetic-event-5",
                    "2026-09-11T22:05:00Z",
                    "Example Cooperative",
                    None,
                    None,
                    "interview_invitation",
                ),
                enabled_sources=("google-calendar",),
            )

            self.assertEqual(result.decision.action, "needs_review")
            self.assertEqual(read_job(workspace, job_id)["status"], "new")
            self.assertTrue(result.receipt_path.is_file())


if __name__ == "__main__":
    unittest.main()
