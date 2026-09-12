import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from career_pipeline.packets import (
    ApplicationManifest,
    collect_local_artifacts,
    complete_local_delivery,
    load_manifest,
    resume_action,
    start_packet,
)
from career_pipeline.workspace import create_workspace
from tests.unit.test_packets import seed_job, synthetic_packet_options
from tests.pdf_helper import write_minimal_pdf
from tests.unit.test_packets import advance_to_saved


class PrepareApplicationIntegrationTests(unittest.TestCase):
    def test_changed_profile_requires_new_version_decision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            _, record = start_packet(
                workspace,
                job_id,
                synthetic_packet_options(profile_hash="old-profile-hash"),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            self.assertEqual(
                resume_action(
                    record,
                    synthetic_packet_options(profile_hash="new-profile-hash"),
                ),
                "restart_required",
            )
            self.assertEqual(
                resume_action(
                    record,
                    synthetic_packet_options(profile_hash="old-profile-hash"),
                ),
                "resume",
            )

    def test_start_packet_cli_loads_workspace_defaults_and_approved_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            preferences = workspace.profile / "Writing_Preferences.md"
            preferences.write_text("Synthetic style\n", encoding="utf-8")
            (workspace.state / "config.json").write_text(
                json.dumps(
                    {
                        "packet_defaults": {
                            "resume_pages": 2,
                            "cover_letter_enabled": False,
                            "cover_letter_pages": 0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            (workspace.state / "onboarding-state.json").write_text(
                json.dumps(
                    {
                        "stage": "active",
                        "profile_hash": "approved-profile-hash",
                        "criteria_hash": "approved-criteria-hash",
                    }
                ),
                encoding="utf-8",
            )
            script = Path(__file__).resolve().parents[2] / "scripts" / "start_packet.py"

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--workspace",
                    str(workspace.root),
                    "--job-id",
                    job_id,
                    "--occurred-at",
                    "2026-09-11T20:05:00Z",
                    "--explicit-request",
                    "--role-instructions",
                    "Emphasize synthetic delivery work.",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            record = load_manifest(
                workspace.state / "application-manifest.json"
            ).packets[job_id][-1]
            self.assertIsNone(record.cover_letter_pdf)
            self.assertEqual(record.profile_hash, "approved-profile-hash")
            self.assertEqual(record.criteria_hash, "approved-criteria-hash")
            self.assertEqual(record.role_instructions, "Emphasize synthetic delivery work.")
            self.assertTrue(record.writing_preferences_hash)

    def test_verify_packet_cli_rejects_modified_delivered_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            manifest, record = start_packet(
                workspace,
                job_id,
                synthetic_packet_options(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            resume = workspace.root / record.resume_pdf
            write_minimal_pdf(resume, pages=2)
            hashes = collect_local_artifacts(workspace, record).hashes
            manifest = advance_to_saved(manifest, job_id, hashes)
            complete_local_delivery(
                workspace,
                manifest,
                job_id,
                occurred_at="2026-09-11T20:10:00Z",
            )
            script = (
                Path(__file__).resolve().parents[2]
                / "scripts"
                / "verify_packet_files.py"
            )

            unchanged = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--workspace",
                    str(workspace.root),
                    "--job-id",
                    job_id,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(unchanged.returncode, 0, unchanged.stdout)

            write_minimal_pdf(resume, pages=1)
            modified = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--workspace",
                    str(workspace.root),
                    "--job-id",
                    job_id,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(modified.returncode, 1, modified.stdout)
            self.assertIn("resume_hash_mismatch", modified.stdout)


if __name__ == "__main__":
    unittest.main()
