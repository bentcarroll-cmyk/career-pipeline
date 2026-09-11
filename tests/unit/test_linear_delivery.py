import tempfile
import unittest
from pathlib import Path

from career_pipeline.linear_delivery import (
    ExportRequestError,
    ExportVerificationError,
    build_linear_export_payload,
    verify_linear_export_readback,
)
from career_pipeline.workspace import create_workspace
from tests.unit.test_packets import seed_job


class LinearExportTests(unittest.TestCase):
    def test_builds_export_only_from_existing_canonical_job(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            payload = build_linear_export_payload(
                workspace,
                job_id,
                {"team_id": "synthetic-team", "project_id": "synthetic-project"},
                explicit_request=True,
            )

            self.assertEqual(payload.job_id, job_id)
            self.assertIn(job_id, payload.title)
            self.assertIn("Evidence-supported strengths", payload.description)
            self.assertEqual(
                payload.application_url,
                "https://jobs.example/apply/SYN-601",
            )

    def test_export_requires_explicit_request_and_existing_job(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            with self.assertRaises(ExportRequestError):
                build_linear_export_payload(
                    workspace,
                    job_id,
                    {"team_id": "synthetic-team", "project_id": "synthetic-project"},
                    explicit_request=False,
                )
            with self.assertRaises(ExportRequestError):
                build_linear_export_payload(
                    workspace,
                    "JOB-999999",
                    {"team_id": "synthetic-team", "project_id": "synthetic-project"},
                    explicit_request=True,
                )

    def test_readback_must_match_exact_destination_and_content(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            payload = build_linear_export_payload(
                workspace,
                job_id,
                {"team_id": "synthetic-team", "project_id": "synthetic-project"},
                explicit_request=True,
            )
            actual = payload.to_readback("SYN-777")
            receipt = verify_linear_export_readback(
                payload,
                actual,
                exported_at="2026-09-11T23:00:00Z",
            )
            self.assertTrue(receipt.verified)
            self.assertEqual(receipt.destination_id, "SYN-777")

            with self.assertRaises(ExportVerificationError):
                verify_linear_export_readback(
                    payload,
                    {**actual, "project_id": "wrong-project"},
                    exported_at="2026-09-11T23:00:00Z",
                )


if __name__ == "__main__":
    unittest.main()
