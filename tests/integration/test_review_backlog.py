import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from career_pipeline.backlog import (
    SelectionError,
    compare_jobs,
    mark_not_pursuing,
    selection_from_request,
)
from career_pipeline.job_store import create_job
from career_pipeline.workspace import create_workspace
from tests.unit.test_job_store import synthetic_assessment, synthetic_candidate


class ReviewBacklogTests(unittest.TestCase):
    def test_explicit_multi_ticket_selection_preserves_order(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            for number in (1, 2):
                candidate = replace(
                    synthetic_candidate(),
                    source_record_id=f"selection-{number}",
                    requisition_id=f"SYN-SELECT-{number}",
                    title=f"Operations Lead {number}",
                    raw_field_hash=f"{number:x}".rjust(64, "0"),
                )
                create_job(
                    workspace,
                    candidate,
                    synthetic_assessment(),
                    posting_markdown="# Synthetic posting\n",
                    assessment_markdown="# Synthetic assessment\n",
                    occurred_at="2026-09-11T18:00:00Z",
                )
            selection = selection_from_request(
                ("JOB-000002", "JOB-000001", "JOB-000002"),
                {"JOB-000001": "Emphasize fictional operations evidence."},
                explicit_request=True,
                workspace=workspace,
            )
            self.assertEqual(selection.job_ids, ("JOB-000002", "JOB-000001"))
            self.assertIn("JOB-000001", selection.per_role_instructions)

    def test_label_state_without_request_cannot_trigger_packet(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            with self.assertRaises(SelectionError):
                selection_from_request(
                    ("JOB-000101",),
                    {},
                    explicit_request=False,
                    workspace=workspace,
                )

    def test_compare_and_not_pursuing_use_canonical_local_records(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            create_job(
                workspace,
                synthetic_candidate(),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T18:20:00Z",
            )

            compared = compare_jobs(workspace, ("JOB-000001",))
            updated = mark_not_pursuing(
                workspace,
                "JOB-000001",
                occurred_at="2026-09-11T18:25:00Z",
            )

            self.assertEqual(compared[0]["employer"], "Example Cooperative")
            self.assertEqual(updated["status"], "not_pursuing")


if __name__ == "__main__":
    unittest.main()
