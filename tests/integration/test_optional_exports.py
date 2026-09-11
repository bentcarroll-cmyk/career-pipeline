import tempfile
import unittest
from pathlib import Path

from career_pipeline.checkpoints import DiscoveryState
from career_pipeline.exports import record_verified_export
from career_pipeline.linear_delivery import (
    ExportVerificationError,
    build_linear_export_payload,
    verify_linear_export_readback,
)
from career_pipeline.job_store import read_job
from career_pipeline.workspace import create_workspace
from tests.unit.test_packets import seed_job


class OptionalExportTests(unittest.TestCase):
    def test_failed_export_does_not_change_any_canonical_workflow_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            before = read_job(workspace, job_id)
            discovery = DiscoveryState(canonical_jobs={"synthetic-key": job_id})
            payload = build_linear_export_payload(
                workspace,
                job_id,
                {"team_id": "synthetic-team", "project_id": "synthetic-project"},
                explicit_request=True,
            )

            with self.assertRaises(ExportVerificationError):
                verify_linear_export_readback(
                    payload,
                    {**payload.to_readback("SYN-778"), "description": "mismatch"},
                    exported_at="2026-09-11T23:05:00Z",
                )

            self.assertEqual(read_job(workspace, job_id), before)
            self.assertEqual(discovery.canonical_jobs["synthetic-key"], job_id)

    def test_verified_export_receipt_is_idempotent_and_never_changes_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            payload = build_linear_export_payload(
                workspace,
                job_id,
                {"team_id": "synthetic-team", "project_id": "synthetic-project"},
                explicit_request=True,
            )
            receipt = verify_linear_export_readback(
                payload,
                payload.to_readback("SYN-779"),
                exported_at="2026-09-11T23:10:00Z",
            )

            first = record_verified_export(
                workspace,
                job_id,
                receipt,
                explicit_request=True,
            )
            second = record_verified_export(
                workspace,
                job_id,
                receipt,
                explicit_request=True,
            )

            self.assertEqual(first, second)
            self.assertEqual(first["status"], "new")
            self.assertEqual(len(first["exports"]), 1)
            self.assertEqual(first["exports"][0]["destination_kind"], "linear")
            events = (workspace.jobs / job_id / "events.jsonl").read_text().splitlines()
            self.assertEqual(len(events), 2)


if __name__ == "__main__":
    unittest.main()
