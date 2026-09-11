import json
import tempfile
import unittest
from pathlib import Path

from career_pipeline.atomic import atomic_write_json, load_json


class AtomicStateTests(unittest.TestCase):
    def test_atomic_write_replaces_complete_document(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "state.json"
            atomic_write_json(path, {"stage": "privacy"})
            atomic_write_json(path, {"stage": "workspace", "schema_version": 1})

            self.assertEqual(
                load_json(path),
                {"schema_version": 1, "stage": "workspace"},
            )
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
