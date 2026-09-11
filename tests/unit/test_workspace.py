import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from career_pipeline.workspace import (
    WorkspaceError,
    create_workspace,
    preserve_source_resume,
)


class WorkspaceTests(unittest.TestCase):
    def test_create_workspace_builds_exact_standard_tree(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "Synthetic-Career"
            paths = create_workspace(root)

            relative_dirs = {
                path.relative_to(root).as_posix()
                for path in root.rglob("*")
                if path.is_dir()
            }
            self.assertEqual(
                relative_dirs,
                {
                    "Profile",
                    "Sources",
                    "Sources/connector-source-notes",
                    "Jobs",
                    "Applications",
                    "Indexes",
                    "Runs",
                    "Runs/discovery",
                    "Runs/lifecycle",
                    "State",
                },
            )
            self.assertEqual(paths.jobs, root.resolve() / "Jobs")
            self.assertEqual(paths.applications, root.resolve() / "Applications")
            self.assertEqual(paths.indexes, root.resolve() / "Indexes")
            self.assertEqual(
                json.loads((paths.state / "next-job-id.json").read_text()),
                {"schema_version": 1, "next_id": 1},
            )

    def test_existing_id_allocation_is_not_reset(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "Synthetic-Career"
            paths = create_workspace(root)
            counter = paths.state / "next-job-id.json"
            counter.write_text(
                '{"schema_version": 1, "next_id": 42}\n',
                encoding="utf-8",
            )

            create_workspace(root)

            self.assertEqual(json.loads(counter.read_text())["next_id"], 42)

    def test_resume_is_preserved_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source = base / "Synthetic_Resume.txt"
            source.write_bytes(b"Synthetic candidate experience\n")
            paths = create_workspace(base / "Synthetic-Career")

            first = preserve_source_resume(source, paths)
            second = preserve_source_resume(source, paths)

            expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(first.sha256, expected_hash)
            self.assertEqual(second.sha256, expected_hash)
            self.assertEqual(first.destination.read_bytes(), source.read_bytes())

            source.write_bytes(b"Changed synthetic candidate experience\n")
            with self.assertRaises(WorkspaceError):
                preserve_source_resume(source, paths)

    def test_workspace_cannot_live_inside_plugin_repository(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        with self.assertRaises(WorkspaceError):
            create_workspace(repository / "Synthetic-Career", repository)


if __name__ == "__main__":
    unittest.main()
