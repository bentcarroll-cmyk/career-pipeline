import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from career_pipeline.backlog import (
    SelectionError,
    _deadline_factor,
    build_actionable_backlog,
    compare_jobs,
    mark_not_pursuing,
    selection_from_request,
)
from career_pipeline.job_store import create_job, update_job_status
from career_pipeline.packets import ApplicationManifest, start_packet
from career_pipeline.timestamps import parse_instant
from career_pipeline.workspace import create_workspace
from tests.unit.test_job_store import synthetic_assessment, synthetic_candidate
from tests.unit.test_packets import synthetic_packet_options


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

    def test_incomplete_packet_is_separate_from_advanced_lifecycle_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = create_job(
                workspace,
                synthetic_candidate(),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T17:00:00Z",
            )["job_id"]
            update_job_status(
                workspace,
                job_id,
                "applied",
                occurred_at="2026-09-11T18:00:00Z",
            )
            before = build_actionable_backlog(
                workspace, as_of="2026-09-11T18:30:00Z"
            )
            start_packet(
                workspace,
                job_id,
                synthetic_packet_options(),
                ApplicationManifest(),
                occurred_at="2026-09-11T19:00:00Z",
                explicit_request=True,
            )

            applied_view = build_actionable_backlog(
                workspace, as_of="2026-09-11T20:00:00Z"
            )
            applied = applied_view["actions"][0]
            update_job_status(
                workspace,
                job_id,
                "interviewing",
                occurred_at="2026-09-11T21:00:00Z",
            )
            interviewing = build_actionable_backlog(
                workspace, as_of="2026-09-11T22:00:00Z"
            )["actions"][0]

            self.assertEqual(applied["status"], "applied")
            self.assertEqual(
                applied["ranking_factors"]["lifecycle_priority"], 700
            )
            self.assertTrue(applied["ranking_factors"]["interrupted_packet"])
            self.assertEqual(applied["packet_stage"], "selected")
            self.assertEqual(applied["packet_version"], "v001")
            self.assertIn("Resume", applied["packet_next_action"])
            self.assertNotEqual(before["source_hash"], applied_view["source_hash"])
            self.assertEqual(interviewing["status"], "interviewing")
            self.assertTrue(
                interviewing["ranking_factors"]["interrupted_packet"]
            )

    def test_tampered_packet_manifest_cannot_create_an_interrupted_action(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = create_job(
                workspace,
                synthetic_candidate(),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T17:00:00Z",
            )["job_id"]
            start_packet(
                workspace,
                job_id,
                synthetic_packet_options(),
                ApplicationManifest(),
                occurred_at="2026-09-11T19:00:00Z",
                explicit_request=True,
            )
            manifest_path = workspace.state / "application-manifest.json"
            tampered = json.loads(manifest_path.read_text(encoding="utf-8"))
            tampered["packets"][job_id][0]["job_id"] = "JOB-999999"
            manifest_path.write_text(json.dumps(tampered), encoding="utf-8")

            with self.assertRaisesRegex(SelectionError, "manifest"):
                build_actionable_backlog(
                    workspace, as_of="2026-09-11T20:00:00Z"
                )

    def test_timed_and_date_only_deadline_boundaries_preserve_precision(self) -> None:
        as_of = parse_instant("2026-09-11T23:00:00Z")

        self.assertEqual(
            _deadline_factor("2026-09-11T23:00:00Z", as_of=as_of),
            (4, "overdue"),
        )
        self.assertEqual(
            _deadline_factor("2026-09-11T09:00:00Z", as_of=as_of),
            (4, "overdue"),
        )
        self.assertEqual(
            _deadline_factor("2026-09-11T05:00:00-04:00", as_of=as_of),
            (4, "overdue"),
        )
        self.assertEqual(
            _deadline_factor("2026-09-11", as_of=as_of),
            (3, "within_3_days"),
        )
        self.assertEqual(
            _deadline_factor("2026-09-14T23:00:00Z", as_of=as_of),
            (3, "within_3_days"),
        )
        self.assertEqual(
            _deadline_factor("2026-09-14T23:00:01Z", as_of=as_of),
            (2, "within_7_days"),
        )
        self.assertEqual(
            _deadline_factor("2026-09-18T23:00:00Z", as_of=as_of),
            (2, "within_7_days"),
        )
        self.assertEqual(
            _deadline_factor("2026-09-18T23:00:01Z", as_of=as_of),
            (1, "within_14_days"),
        )
        self.assertEqual(
            _deadline_factor("2026-09-25T23:00:00Z", as_of=as_of),
            (1, "within_14_days"),
        )
        self.assertEqual(
            _deadline_factor("2026-09-25T23:00:01Z", as_of=as_of),
            (0, None),
        )

    def test_expired_deadline_recommends_verifying_that_role_is_open(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            create_job(
                workspace,
                replace(
                    synthetic_candidate(),
                    deadline="2026-09-11T09:00:00Z",
                ),
                replace(synthetic_assessment(), uncertainties=()),
                posting_markdown="# Synthetic posting\n",
                assessment_markdown="# Synthetic assessment\n",
                occurred_at="2026-09-11T17:00:00Z",
            )

            action = build_actionable_backlog(
                workspace, as_of="2026-09-11T23:00:00Z"
            )["actions"][0]

            self.assertEqual(
                action["ranking_factors"]["deadline_urgency"], "overdue"
            )
            self.assertIn("remains open", action["recommended_next_action"])
            self.assertNotIn(
                "before its recorded deadline", action["recommended_next_action"]
            )

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
