import tempfile
import unittest
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


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_recency_uses_instants_instead_of_timestamp_text(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = create_workspace(Path(raw) / "Synthetic-Career")
            merge_discovery_state(
                workspace,
                DiscoveryState(),
                (
                    (
                        "greenhouse",
                        SourceResult(
                            True,
                            "2026-09-11T12:30:00+00:00",
                            ("SYN-OLD",),
                            "old",
                        ),
                    ),
                ),
            )

            merged = merge_discovery_state(
                workspace,
                DiscoveryState(),
                (
                    (
                        "greenhouse",
                        SourceResult(
                            True,
                            "2026-09-11T09:00:00-04:00",
                            ("SYN-NEW",),
                            "new",
                        ),
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
                        SourceResult(True, "2026-09-11T12:00:00Z", ("SYN-1",), "a"),
                    ),
                ),
            )
            second = merge_discovery_state(
                workspace,
                DiscoveryState(canonical_jobs={"req:example:syn-2": "JOB-000002"}),
                (
                    (
                        "public-search",
                        SourceResult(True, "2026-09-11T12:01:00Z", ("SYN-2",), "b"),
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
