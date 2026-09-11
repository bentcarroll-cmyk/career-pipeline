import hashlib
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
                    "Applications",
                    "Runs",
                    "Runs/discovery",
                    "Runs/lifecycle",
                    "State",
                },
            )
            self.assertEqual(paths.applications, root.resolve() / "Applications")

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
