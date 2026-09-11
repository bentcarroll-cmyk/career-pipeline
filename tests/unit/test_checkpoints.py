import unittest

from career_pipeline.checkpoints import (
    DiscoveryState,
    SourceCheckpoint,
    SourceResult,
    complete_source,
)


class CheckpointTests(unittest.TestCase):
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
