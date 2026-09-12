from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_environment.py"


class EnvironmentPreflightTests(unittest.TestCase):
    def run_preflight(self, package: Path, *, unsupported_python: bool = False):
        command = [sys.executable, "-S", str(SCRIPT), str(package)]
        if unsupported_python:
            command = [
                sys.executable,
                "-S",
                "-c",
                "import runpy, sys; sys.version_info = (3, 9, 6); "
                "sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')",
                str(SCRIPT),
                str(package),
            ]
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def copy_package(self, temporary: Path) -> Path:
        package = temporary / "plugin"
        for name in (".codex-plugin", ".agents", "src"):
            shutil.copytree(ROOT / name, package / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(ROOT / "pyproject.toml", package / "pyproject.toml")
        return package

    def test_supported_python_checks_package_without_writing_or_importing_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = self.copy_package(Path(raw))
            initializer = package / "src" / "career_pipeline" / "__init__.py"
            with initializer.open("a", encoding="utf-8") as stream:
                stream.write("\nraise RuntimeError('preflight must not execute package code')\n")
            before = {path.relative_to(package): path.read_bytes() for path in package.rglob("*") if path.is_file()}

            result = self.run_preflight(package)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("career-pipeline-private-beta", result.stdout)
            self.assertIn("Codex CLI", result.stdout)
            after = {path.relative_to(package): path.read_bytes() for path in package.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

    def test_unsupported_python_stops_before_reading_package(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = self.run_preflight(Path(raw) / "missing", unsupported_python=True)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Python 3.11", result.stdout)
        self.assertIn("3.9.6", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_non_posix_platform_fails_before_reporting_readiness(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import runpy, sys; from types import SimpleNamespace; "
                "sys.argv = sys.argv[1:]; entry = runpy.run_path(sys.argv[0])['main']; "
                "entry.__globals__['os'] = SimpleNamespace(name='nt'); "
                "raise SystemExit(entry())",
                str(SCRIPT),
                str(ROOT),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Windows", result.stdout)
        self.assertIn("macOS", result.stdout)
        self.assertNotIn("PASS:", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_fcntl_fails_before_reporting_readiness(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import runpy, sys; sys.modules['fcntl'] = None; "
                "sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')",
                str(SCRIPT),
                str(ROOT),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("fcntl", result.stdout)
        self.assertNotIn("PASS:", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_runtime_file_fails_with_actionable_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = self.copy_package(Path(raw))
            (package / "src" / "career_pipeline" / "workspace.py").unlink()

            result = self.run_preflight(package)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("workspace.py", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_package_fails_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = self.run_preflight(Path(raw) / "not-extracted")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("not-extracted", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_mixed_release_versions_fail(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = self.copy_package(Path(raw))
            manifest_path = package / ".codex-plugin" / "plugin.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["version"] = "999.0.0"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = self.run_preflight(package)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("version", result.stdout.lower())
        self.assertNotIn("Traceback", result.stderr)

    def test_wrong_marketplace_identity_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = self.copy_package(Path(raw))
            manifest_path = package / ".agents" / "plugins" / "marketplace.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["name"] = "unrelated-marketplace"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = self.run_preflight(package)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("marketplace", result.stdout.lower())
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_on_path_is_reported_without_executing_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            temporary = Path(raw)
            executable = temporary / "codex"
            marker = temporary / "executed"
            executable.write_text(f"#!/bin/sh\nprintf invoked > '{marker}'\nexit 55\n", encoding="utf-8")
            executable.chmod(0o755)
            environment = dict(os.environ, PATH=str(temporary))

            result = subprocess.run(
                [sys.executable, "-S", str(SCRIPT), str(ROOT)],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(str(executable), result.stdout)
            self.assertFalse(marker.exists())

    def test_missing_cli_gives_guidance_without_failing_package_check(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import runpy, sys; from unittest.mock import patch; "
                "sys.argv = sys.argv[1:]; "
                "patch('shutil.which', return_value=None).start(); "
                "patch('os.access', return_value=False).start(); "
                "runpy.run_path(sys.argv[0], run_name='__main__')",
                str(SCRIPT),
                str(ROOT),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Codex CLI was not found", result.stdout)
        self.assertIn("Desktop", result.stdout)


if __name__ == "__main__":
    unittest.main()
