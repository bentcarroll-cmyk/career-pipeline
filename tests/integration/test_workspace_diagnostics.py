import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from career_pipeline.workspace import create_workspace
from tests.unit.test_job_contract import valid_job


ROOT = Path(__file__).resolve().parents[2]


class WorkspaceDiagnosticsTests(unittest.TestCase):
    def test_diagnostic_reports_repair_codes_without_private_content(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            (workspace.state / "config.json").write_text(
                json.dumps({"schema_version": 2, "private_marker": "synthetic-private-value"}),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "diagnose_workspace.py"), "--root", str(workspace.root)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("config.required_field", result.stdout)
        self.assertIn("config.unexpected_field", result.stdout)
        self.assertNotIn("synthetic-private-value", result.stdout)
        self.assertNotIn(raw, result.stdout)

    def test_diagnostic_scans_runs_source_receipts_lifecycle_and_job_events(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            discovery = workspace.runs / "discovery"
            sources = discovery / "sources"
            lifecycle = workspace.runs / "lifecycle"
            sources.mkdir()
            (discovery / "run-synthetic.json").write_text(
                json.dumps({"schema_version": True}), encoding="utf-8"
            )
            (sources / ("receipt-" + "a" * 64 + ".json")).write_text(
                json.dumps({"schema_version": True}), encoding="utf-8"
            )
            (lifecycle / "receipt-synthetic.json").write_text(
                json.dumps({"private_marker": "synthetic-private-value"}),
                encoding="utf-8",
            )
            job = workspace.jobs / "JOB-000001"
            job.mkdir()
            (job / "job.json").write_text("{}", encoding="utf-8")
            (job / "events.jsonl").write_text(
                json.dumps({"schema_version": True}) + "\n", encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "diagnose_workspace.py"),
                    "--root",
                    str(workspace.root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 1)
        for persisted_type in (
            "discovery-run",
            "discovery-evidence-receipt",
            "lifecycle-receipt",
            "job-event",
        ):
            self.assertIn(persisted_type + ".", result.stdout)
        self.assertNotIn("synthetic-private-value", result.stdout)
        self.assertNotIn(raw, result.stdout)

    def test_diagnostic_enforces_job_path_identity_binding(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job = workspace.jobs / "JOB-000001"
            job.mkdir()
            record = valid_job()
            record["job_id"] = "JOB-000001"
            record["paths"] = {
                "posting": "Jobs/JOB-000002/posting.md",
                "assessment": "Jobs/JOB-000001/assessment.md",
                "events": "Jobs/JOB-000001/events.jsonl",
                "working": "Jobs/JOB-000001/working",
            }
            (job / "job.json").write_text(json.dumps(record), encoding="utf-8")
            (job / "events.jsonl").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "event_type": "created",
                        "occurred_at": "2026-09-11T12:00:00Z",
                        "job_id": "JOB-000001",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "diagnose_workspace.py"),
                    "--root",
                    str(workspace.root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("job.job_path_mismatch", result.stdout)
        self.assertNotIn(raw, result.stdout)


if __name__ == "__main__":
    unittest.main()
