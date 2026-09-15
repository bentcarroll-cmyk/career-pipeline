import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from career_pipeline.checkpoints import (
    DiscoveryState,
    SourceCheckpoint,
    SourceResult,
    complete_source,
    load_discovery_state,
    merge_discovery_state,
    save_discovery_state,
)
from career_pipeline.workspace import create_workspace
from tests.retrieval_fixtures import completed_board_result


class CheckpointTests(unittest.TestCase):
    def test_duplicate_source_results_cannot_hide_invalid_success_before_merge(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            valid = completed_board_result(workspace, "greenhouse", "SYN-1", "2026-09-11T12:00:00Z")
            merge_discovery_state(workspace, DiscoveryState(), (("greenhouse", valid),))
            path = workspace.state / "discovery-state.json"
            before = path.read_bytes()
            invalid = replace(valid, completed_at="2026-09-11T13:00:00Z",
                              seen_records=("never-returned",), cursor="bogus")
            with self.assertRaisesRegex(ValueError, "duplicate_source"):
                merge_discovery_state(workspace,
                    DiscoveryState(canonical_jobs={"req:unwritten:1": "JOB-000009"}),
                    (("greenhouse", invalid), ("greenhouse", valid)))
            self.assertEqual(path.read_bytes(), before)

    def test_mixed_source_completion_instants_are_order_independent_and_ignore_failed_timestamp(self) -> None:
        from career_pipeline import retrieval
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            greenhouse = completed_board_result(workspace, "greenhouse", "SYN-1", "2026-09-11T12:00:00Z")
            scope = retrieval.register_scope(workspace, run_id="mixed", source="ashby", provider="ashby",
                query={"board": "example", "employer": "Example"}, now="2026-09-11T12:30:00Z")
            scope = retrieval.capture_response(workspace, scope["scope_id"], {"jobs": []}, now="2026-09-11T12:30:00Z")
            ashby = SourceResult(True, "2026-09-11T13:00:00Z", (), None, tuple(scope["intake_ids"]), (scope["scope_id"],))
            failed = SourceResult(False, "unparseable partial timestamp", (), "retry")
            for results in ((("greenhouse", greenhouse), ("ashby", ashby)),
                            (("ashby", ashby), ("greenhouse", greenhouse)),
                            (("indeed", failed), ("greenhouse", greenhouse), ("ashby", ashby))):
                with self.subTest(order=[source for source, _ in results]):
                    merged = merge_discovery_state(workspace, DiscoveryState(), results)
                    self.assertEqual(merged.sources["greenhouse"].last_successful_at, "2026-09-11T12:00:00Z")
                    self.assertEqual(merged.sources["ashby"].last_successful_at, "2026-09-11T13:00:00Z")
                    self.assertNotIn("indeed", merged.sources)

    def test_checkpoint_recency_uses_instants_instead_of_timestamp_text(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            merge_discovery_state(
                workspace,
                DiscoveryState(),
                (
                    (
                        "greenhouse",
                        completed_board_result(workspace, "greenhouse", "SYN-OLD",
                            "2026-09-11T12:30:00+00:00", cursor="old"),
                    ),
                ),
            )

            merged = merge_discovery_state(
                workspace,
                DiscoveryState(),
                (
                    (
                        "greenhouse",
                        completed_board_result(workspace, "greenhouse", "SYN-NEW",
                            "2026-09-11T09:00:00-04:00", cursor="new"),
                    ),
                ),
            )

            self.assertEqual(merged.sources["greenhouse"].cursor, "new")
            self.assertEqual(
                merged.sources["greenhouse"].seen_records,
                ("SYN-NEW",),
            )

    def test_stale_runs_merge_independent_source_and_identity_updates(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            first = merge_discovery_state(
                workspace,
                DiscoveryState(canonical_jobs={"req:example:syn-1": "JOB-000001"}),
                (
                    (
                        "greenhouse",
                        completed_board_result(workspace, "greenhouse", "SYN-1", "2026-09-11T12:00:00Z", cursor="a"),
                    ),
                ),
            )
            second = merge_discovery_state(
                workspace,
                DiscoveryState(canonical_jobs={"req:example:syn-2": "JOB-000002"}),
                (
                    (
                        "public-search",
                        completed_board_result(workspace, "public-search", "SYN-2", "2026-09-11T12:01:00Z", cursor="b"),
                    ),
                ),
            )

            self.assertEqual(set(second.sources), {"greenhouse", "public-search"})
            self.assertEqual(
                second.canonical_jobs,
                {
                    "req:example:syn-1": "JOB-000001",
                    "req:example:syn-2": "JOB-000002",
                },
            )
            self.assertEqual(
                load_discovery_state(
                    workspace.state / "discovery-state.json"
                ),
                second,
            )
            self.assertIn("greenhouse", first.sources)

    def test_discovery_state_round_trips_all_source_and_local_identity_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "discovery-state.json"
            state = DiscoveryState(
                sources={
                    "public-search": SourceCheckpoint(
                        "2026-09-11T12:00:00Z",
                        ("synthetic-record",),
                        "synthetic-cursor",
                    )
                },
                stable_review_batch="a" * 64,
                canonical_jobs={"req:example:syn-1": "JOB-000001"},
            )

            save_discovery_state(path, state)

            self.assertEqual(load_discovery_state(path), state)

    def test_failed_source_does_not_advance_checkpoint(self) -> None:
        before = DiscoveryState(
            sources={
                "indeed": SourceCheckpoint(
                    last_successful_at="2026-09-10T12:00:00Z",
                    seen_records=("old-record",),
                    cursor="cursor-1",
                )
            }
        )
        after = complete_source(
            before,
            "indeed",
            SourceResult(
                success=False,
                completed_at="2026-09-11T12:00:00Z",
                seen_records=("new-record",),
                cursor="cursor-2",
            ),
        )
        self.assertEqual(after, before)

    def test_success_advances_only_selected_source(self) -> None:
        before = DiscoveryState(
            sources={
                "indeed": SourceCheckpoint(None, (), None),
                "greenhouse": SourceCheckpoint(None, (), None),
            }
        )
        after = complete_source(
            before,
            "greenhouse",
            SourceResult(True, "2026-09-11T12:00:00Z", ("SYN-1",), "next"),
        )
        self.assertEqual(after.sources["indeed"], before.sources["indeed"])
        self.assertEqual(after.sources["greenhouse"].cursor, "next")


if __name__ == "__main__":
    unittest.main()
