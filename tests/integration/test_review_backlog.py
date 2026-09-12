import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from career_pipeline.backlog import (
    SelectionError,
    build_actionable_backlog,
    compare_jobs,
    mark_not_pursuing,
    selection_from_request,
)
from career_pipeline.job_store import create_job
from career_pipeline.workspace import create_workspace
from tests.unit.test_job_store import synthetic_assessment, synthetic_candidate


class ReviewBacklogTests(unittest.TestCase):
    def _create_ranked_jobs(self, workspace) -> None:
        fixtures = (
            (1, "offer", None, "strong_match", (), ()),
            (2, "prepare_application", "2026-09-12", "strong_match", ("Domain gap",), ()),
            (3, "needs_confirmation", "2026-09-13", "worth_considering", (), ("Travel unknown",)),
            (4, "new", "2026-09-12", "strong_match", (), ()),
            (5, "not_pursuing", "2026-09-11", "strong_match", (), ()),
            (6, "new", None, "worth_considering", (), ()),
        )
        for number, status, deadline, disposition, gaps, uncertainties in fixtures:
            candidate = replace(
                synthetic_candidate(),
                source_record_id=f"backlog-{number}",
                requisition_id=f"SYN-BACKLOG-{number}",
                title=f"Synthetic Role {number}",
                deadline=deadline,
                verified_at=f"2026-09-{number + 1:02d}T12:00:00Z",
                raw_field_hash=f"{number:x}".rjust(64, "0"),
            )
            assessment = replace(
                synthetic_assessment(),
                disposition=disposition,
                gaps=gaps,
                uncertainties=uncertainties,
                role_to_profile_fit=f"Synthetic fit reason {number}.",
            )
            record = create_job(
                workspace,
                candidate,
                assessment,
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at=f"2026-09-{number + 1:02d}T12:05:00Z",
            )
            if status != "new":
                from career_pipeline.job_store import update_job_status

                update_job_status(
                    workspace,
                    record["job_id"],
                    status,
                    occurred_at=f"2026-09-{number + 1:02d}T13:00:00Z",
                )

    def test_actionable_view_is_ranked_from_canonical_active_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            self._create_ranked_jobs(workspace)

            view = build_actionable_backlog(
                workspace, as_of="2026-09-11T16:00:00Z"
            )

            self.assertEqual(
                [item["job_id"] for item in view["actions"]],
                [
                    "JOB-000001",
                    "JOB-000002",
                    "JOB-000003",
                    "JOB-000004",
                    "JOB-000006",
                ],
            )
            self.assertEqual(view["actions"][0]["status"], "offer")
            self.assertEqual(
                view["actions"][0]["fit_reason"], "Synthetic fit reason 1."
            )
            self.assertIsNone(view["actions"][0]["major_gap"])
            self.assertIsNone(view["actions"][0]["deadline"])
            interrupted = view["actions"][1]
            self.assertTrue(interrupted["ranking_factors"]["interrupted_packet"])
            self.assertIn("interrupted", interrupted["recommended_next_action"])
            confirmation = view["actions"][2]
            self.assertEqual(
                confirmation["facts_needing_confirmation"], ["Travel unknown"]
            )
            self.assertIsNone(confirmation["major_gap"])
            self.assertEqual(
                confirmation["source_freshness"],
                {"verified_at": "2026-09-04T12:00:00Z", "reverified_at": None},
            )
            self.assertNotIn("JOB-000005", json.dumps(view))
            self.assertGreater(
                view["actions"][3]["ranking_factors"]["deadline_priority"],
                view["actions"][4]["ranking_factors"]["deadline_priority"],
            )
            self.assertEqual(view, build_actionable_backlog(workspace, as_of="2026-09-11T16:00:00Z"))

    def test_actionable_view_ignores_a_tampered_disposable_view(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            self._create_ranked_jobs(workspace)
            destination = workspace.indexes / "actionable-backlog.json"
            destination.write_text('{"fabricated": true}\n', encoding="utf-8")

            view = build_actionable_backlog(
                workspace, as_of="2026-09-11T16:00:00Z"
            )

            self.assertNotIn("fabricated", view)
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), view)

    def test_review_backlog_cli_renders_human_readable_actions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            self._create_ranked_jobs(workspace)
            root = Path(__file__).resolve().parents[2]

            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts" / "review_backlog.py"),
                    "--workspace",
                    str(workspace.root),
                    "--as-of",
                    "2026-09-11T16:00:00Z",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("JOB-000001", result.stdout)
            self.assertIn("Synthetic fit reason 1.", result.stdout)
            self.assertIn("Deadline: unknown", result.stdout)
            self.assertIn("Confirm: Travel unknown", result.stdout)

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
