import json
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch
from pathlib import Path

from career_pipeline.packets import (
    ApplicationManifest,
    InvalidPacketTransition,
    PacketOptions,
    advance_packet,
    collect_local_artifacts,
    complete_local_delivery,
    load_manifest,
    persist_manifest,
    restart_packet,
    resume_queue,
    save_manifest,
    start_packet,
)
from career_pipeline.job_store import create_job, read_job, update_job_status
from career_pipeline.workspace import create_workspace
from tests.unit.test_job_store import synthetic_assessment, synthetic_candidate
from tests.unit.test_packets import seed_job
from tests.pdf_helper import write_minimal_pdf
from tests.unit.test_packets import advance_to_saved, synthetic_packet_options


class PacketResumptionTests(unittest.TestCase):
    def test_stale_caller_manifest_merges_with_existing_job_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            first_job = seed_job(workspace)
            second_job = create_job(
                workspace,
                replace(
                    synthetic_candidate(),
                    source_record_id="synthetic-record-2",
                    requisition_id="SYN-602",
                    title="Strategy Operations Lead",
                    raw_field_hash="b" * 64,
                ),
                synthetic_assessment(),
                posting_markdown="# Synthetic posting two\n",
                assessment_markdown="# Synthetic assessment two\n",
                occurred_at="2026-09-11T20:01:00Z",
            )["job_id"]
            start_packet(
                workspace,
                first_job,
                synthetic_packet_options(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )

            merged, _ = start_packet(
                workspace,
                second_job,
                synthetic_packet_options(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:06:00Z",
                explicit_request=True,
            )

            self.assertEqual(set(merged.packets), {first_job, second_job})
            persisted = load_manifest(
                workspace.state / "application-manifest.json"
            )
            self.assertEqual(set(persisted.packets), {first_job, second_job})

    def test_directory_creation_failure_keeps_recoverable_version_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            with patch(
                "career_pipeline.packets._ensure_packet_directories",
                side_effect=OSError("synthetic interruption"),
            ):
                with self.assertRaises(OSError):
                    tape = ApplicationManifest()
                    start_packet(
                        workspace,
                        job_id,
                        synthetic_packet_options(),
                        tape,
                        occurred_at="2026-09-11T20:05:00Z",
                        explicit_request=True,
                    )

            recovered, record = start_packet(
                workspace,
                job_id,
                synthetic_packet_options(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:06:00Z",
                explicit_request=True,
            )

            self.assertEqual(record.version, "v001")
            self.assertEqual(recovered.packets[job_id][-1].version, "v001")
            self.assertTrue((workspace.root / record.working_dir).is_dir())

    def test_retry_after_lost_return_reuses_persisted_version_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)

            _, first = start_packet(
                workspace,
                job_id,
                synthetic_packet_options(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            recovered, second = start_packet(
                workspace,
                job_id,
                synthetic_packet_options(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:06:00Z",
                explicit_request=True,
            )

            self.assertEqual(first.version, "v001")
            self.assertEqual(second.version, "v001")
            self.assertEqual(recovered.packets[job_id][-1], first)
            self.assertTrue(
                (workspace.state / "application-manifest.json").is_file()
            )

    def test_interrupted_packet_round_trips_and_resumes_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            manifest, _ = start_packet(
                workspace,
                job_id,
                synthetic_packet_options(),
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            manifest = advance_packet(
                manifest,
                job_id,
                "posting_verified",
                {
                    "posting_url": "https://jobs.example/postings/SYN-601",
                    "application_url": "https://jobs.example/apply/SYN-601",
                    "posting_snapshot_hash": "b" * 64,
                },
            )
            path = workspace.state / "application-manifest.json"
            save_manifest(path, manifest)
            loaded = load_manifest(path)
            self.assertEqual(loaded, manifest)
            self.assertEqual([record.job_id for record in resume_queue(loaded)], [job_id])

            unchanged, record = start_packet(
                workspace,
                job_id,
                synthetic_packet_options(),
                loaded,
                occurred_at="2026-09-11T20:10:00Z",
                explicit_request=True,
            )
            self.assertEqual(unchanged, loaded)
            self.assertEqual(record.version, "v001")

    def test_changed_packet_inputs_require_restart_and_preserve_interrupted_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            first_options = synthetic_packet_options()
            _, first = start_packet(
                workspace,
                job_id,
                first_options,
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            changed = synthetic_packet_options(
                profile_hash="profile-hash-v2",
                cover_letter_enabled=True,
                cover_letter_pages=1,
                role_instructions="Use corrected synthetic evidence.",
            )

            with self.assertRaisesRegex(ValueError, "restart required"):
                start_packet(
                    workspace,
                    job_id,
                    changed,
                    ApplicationManifest(),
                    occurred_at="2026-09-11T20:06:00Z",
                    explicit_request=True,
                )
            restarted, second = restart_packet(
                workspace,
                job_id,
                changed,
                ApplicationManifest(),
                occurred_at="2026-09-11T20:07:00Z",
                explicit_request=True,
            )

            self.assertEqual((first.version, second.version), ("v001", "v002"))
            self.assertEqual(len(restarted.packets[job_id]), 2)
            self.assertEqual(restarted.packets[job_id][0], first)
            self.assertEqual(second.profile_hash, "profile-hash-v2")
            self.assertEqual(second.role_instructions, "Use corrected synthetic evidence.")
            self.assertTrue(second.packet_options["cover_letter_enabled"])

    def test_every_bound_input_is_compared_before_resume(self) -> None:
        changes = (
            {"profile_hash": "profile-hash-v2"},
            {"criteria_hash": "criteria-hash-v2"},
            {"writing_preferences_hash": "writing-hash-v2"},
            {"resume_pages": 3},
            {"role_instructions": "Different role emphasis."},
        )
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as raw:
                workspace = create_workspace(Path(raw) / "Synthetic-Career")
                job_id = seed_job(workspace)
                start_packet(
                    workspace,
                    job_id,
                    synthetic_packet_options(),
                    ApplicationManifest(),
                    occurred_at="2026-09-11T20:05:00Z",
                    explicit_request=True,
                )
                with self.assertRaisesRegex(ValueError, "restart required"):
                    start_packet(
                        workspace,
                        job_id,
                        synthetic_packet_options(**change),
                        ApplicationManifest(),
                        occurred_at="2026-09-11T20:06:00Z",
                        explicit_request=True,
                    )

    def test_delivery_replay_converges_after_each_persistence_boundary(self) -> None:
        import career_pipeline.packets as packets_module

        boundaries = (
            ("local_verified_manifest", "persist_manifest", 1),
            ("canonical_application", "record_application_version", 1),
            ("ready_manifest", "persist_manifest", 2),
        )
        for boundary, target, fail_call in boundaries:
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as raw:
                workspace = create_workspace(Path(raw) / "Synthetic-Career")
                job_id = seed_job(workspace)
                options = synthetic_packet_options()
                manifest, record = start_packet(
                    workspace,
                    job_id,
                    options,
                    ApplicationManifest(),
                    occurred_at="2026-09-11T20:05:00Z",
                    explicit_request=True,
                )
                write_minimal_pdf(workspace.root / record.resume_pdf, pages=2)
                hashes = collect_local_artifacts(workspace, record).hashes
                manifest = advance_to_saved(manifest, job_id, hashes)
                save_manifest(workspace.state / "application-manifest.json", manifest)
                original = getattr(packets_module, target)
                calls = 0

                def interrupt_after_write(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    result = original(*args, **kwargs)
                    if calls == fail_call:
                        raise OSError(f"synthetic interruption after {boundary}")
                    return result

                with patch.object(
                    packets_module,
                    target,
                    side_effect=interrupt_after_write,
                ):
                    with self.assertRaises(OSError):
                        complete_local_delivery(
                            workspace,
                            manifest,
                            job_id,
                            occurred_at="2026-09-11T20:10:00Z",
                        )

                persisted = load_manifest(
                    workspace.state / "application-manifest.json"
                )
                resumed, _ = start_packet(
                    workspace,
                    job_id,
                    options,
                    persisted,
                    occurred_at="2026-09-11T20:11:00Z",
                    explicit_request=True,
                )
                completed = complete_local_delivery(
                    workspace,
                    resumed,
                    job_id,
                    occurred_at="2026-09-11T20:12:00Z",
                )

                canonical = read_job(workspace, job_id)
                self.assertEqual(canonical["status"], "packet_ready")
                self.assertEqual(len(canonical["application_versions"]), 1)
                self.assertEqual(completed.packets[job_id][-1].stage, "ready")
                events = [
                    json.loads(line)
                    for line in (
                        workspace.jobs / job_id / "events.jsonl"
                    ).read_text(encoding="utf-8").splitlines()
                ]
                deliveries = [
                    event
                    for event in events
                    if event["metadata"].get("version") == "v001"
                ]
                self.assertEqual(len(deliveries), 1)

    def test_delivery_replay_preserves_later_and_not_pursuing_statuses(self) -> None:
        for status in ("applied", "interviewing", "offer", "not_pursuing", "closed"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as raw:
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
                update_job_status(
                    workspace,
                    job_id,
                    status,
                    occurred_at="2026-09-11T20:06:00Z",
                )
                write_minimal_pdf(workspace.root / record.resume_pdf, pages=2)
                hashes = collect_local_artifacts(workspace, record).hashes
                manifest = advance_to_saved(manifest, job_id, hashes)
                complete_local_delivery(
                    workspace,
                    manifest,
                    job_id,
                    occurred_at="2026-09-11T20:10:00Z",
                )
                self.assertEqual(read_job(workspace, job_id)["status"], status)

    def test_ready_manifest_reconciles_existing_application_before_status_work(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            options = synthetic_packet_options()
            manifest, record = start_packet(
                workspace,
                job_id,
                options,
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            write_minimal_pdf(workspace.root / record.resume_pdf, pages=2)
            hashes = collect_local_artifacts(workspace, record).hashes
            manifest = advance_to_saved(manifest, job_id, hashes)
            ready = complete_local_delivery(
                workspace,
                manifest,
                job_id,
                occurred_at="2026-09-11T20:10:00Z",
            )
            update_job_status(
                workspace,
                job_id,
                "prepare_application",
                occurred_at="2026-09-11T20:11:00Z",
            )

            resumed, record = start_packet(
                workspace,
                job_id,
                options,
                ready,
                occurred_at="2026-09-11T20:12:00Z",
                explicit_request=True,
            )
            replayed = complete_local_delivery(
                workspace,
                resumed,
                job_id,
                occurred_at="2026-09-11T20:13:00Z",
            )

            self.assertEqual(record.version, "v001")
            self.assertEqual(replayed.packets[job_id][-1].stage, "ready")
            self.assertEqual(read_job(workspace, job_id)["status"], "packet_ready")

    def test_superseded_saved_version_cannot_deliver_as_newer_selected_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            options = synthetic_packet_options()
            v1_manifest, v1 = start_packet(
                workspace,
                job_id,
                options,
                ApplicationManifest(),
                occurred_at="2026-09-11T20:05:00Z",
                explicit_request=True,
            )
            write_minimal_pdf(workspace.root / v1.resume_pdf, pages=2)
            hashes = collect_local_artifacts(workspace, v1).hashes
            v1_manifest = advance_to_saved(v1_manifest, job_id, hashes)
            persist_manifest(workspace, v1_manifest)
            combined, v2 = restart_packet(
                workspace,
                job_id,
                options,
                ApplicationManifest(),
                occurred_at="2026-09-11T20:06:00Z",
                explicit_request=True,
            )
            self.assertEqual(v2.version, "v002")

            with self.assertRaisesRegex(InvalidPacketTransition, "superseded"):
                complete_local_delivery(
                    workspace,
                    v1_manifest,
                    job_id,
                    occurred_at="2026-09-11T20:10:00Z",
                )

            canonical = read_job(workspace, job_id)
            self.assertEqual(canonical["application_versions"], [])
            persisted = load_manifest(
                workspace.state / "application-manifest.json"
            )
            self.assertEqual(persisted, combined)
            self.assertEqual(persisted.packets[job_id][-1].stage, "selected")

    def test_interleaved_normal_starts_share_one_version_reservation(self) -> None:
        import career_pipeline.packets as packets_module

        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            job_id = seed_job(workspace)
            options = synthetic_packet_options()
            original_update = packets_module.update_job_status
            nested_result = []
            interleaved = False

            def interleave_second_start(*args, **kwargs):
                nonlocal interleaved
                result = original_update(*args, **kwargs)
                if not interleaved:
                    interleaved = True
                    nested_result.append(
                        start_packet(
                            workspace,
                            job_id,
                            options,
                            ApplicationManifest(),
                            occurred_at="2026-09-11T20:05:01Z",
                            explicit_request=True,
                        )[1]
                    )
                return result

            with patch.object(
                packets_module,
                "update_job_status",
                side_effect=interleave_second_start,
            ):
                manifest, outer = start_packet(
                    workspace,
                    job_id,
                    options,
                    ApplicationManifest(),
                    occurred_at="2026-09-11T20:05:00Z",
                    explicit_request=True,
                )

            self.assertEqual(outer.version, "v001")
            self.assertEqual(nested_result[0].version, "v001")
            self.assertEqual(len(manifest.packets[job_id]), 1)


if __name__ == "__main__":
    unittest.main()
