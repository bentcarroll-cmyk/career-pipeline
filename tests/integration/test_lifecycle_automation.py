import json
import tempfile
import unittest
from pathlib import Path

from career_pipeline.automation_policy import render_automation
from career_pipeline.job_store import create_job, read_job
from career_pipeline.reconciliation import (
    LifecycleEvidence,
    reconcile_lifecycle_evidence,
)
from career_pipeline.workspace import create_workspace
from tests.unit.test_job_store import synthetic_assessment, synthetic_candidate


class LifecycleAutomationTests(unittest.TestCase):
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
