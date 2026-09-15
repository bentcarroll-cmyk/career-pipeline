from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from career_pipeline.workspace import create_workspace


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "discovery_retrieval.py"

SUBPROCESS_IMPORT = """
import importlib.util, json, sys
from unittest.mock import patch
spec = importlib.util.spec_from_file_location("retrieval_cli", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
"""


def indeed_response(count=10, total=840, *, description=True):
    return {
        "content": [{"type": "text", "text": f"Found {count} jobs"}],
        "structuredContent": {
            "resultsShown": count,
            "totalAvailable": total,
            "totalApproximate": "800+",
            "search": "operations",
            "location": "Remote",
            "jobs": [
                {
                    "jrtk": f"result-{number}",
                    "company": "Synthetic Cooperative",
                    "title": f"Operations Lead {number}",
                    "location": "Remote US",
                    "url": f"https://example.test/jobs/{number}",
                    "description": "Lead customer operations and improve workflows." if description else "",
                    "salary": None,
                    "job_type": "Full-time",
                }
                for number in range(count)
            ],
        },
    }


class RetrievalCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = create_workspace(self.root / "Synthetic-Career")

    def document(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def cli(self, *arguments, success=True, output=None):
        self.assertTrue(SCRIPT.is_file(), "Retrieval CLI must account for source scopes and raw responses")
        command = [sys.executable, str(SCRIPT), "--workspace", str(self.workspace.root)]
        if output:
            command += ["--output", str(output)]
        result = subprocess.run(command + list(arguments), capture_output=True, text=True, check=False)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(output.read_text() if output else result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        error = json.loads(result.stderr)
        self.assertTrue(error.get("error"))
        return error

    def register(self, *, provider="indeed", source="indeed", query=None):
        path = self.document("query.json", query or {"search": "operations", "location": "Remote"})
        return self.cli("register", "--run-id", "synthetic-run", "--source", source,
                        "--provider", provider, "--query", str(path))

    def collect_with_responses(self, scope_id, responses, *, success=True):
        # Replace only the external fetch boundary; parsing, raw persistence,
        # intake, locking, cursor state, and CLI error handling remain real.
        fixture = self.document("network-pages.json", responses)
        code = SUBPROCESS_IMPORT + """
pages = json.loads(open(sys.argv[2]).read())
def fetch(provider, *, query, cursor=None):
    value = pages.get(str(cursor), {"error": "unexpected network request"})
    if isinstance(value, dict) and "error" in value:
        raise OSError(value["error"])
    return value
with patch("career_pipeline.collectors.fetch_board_page", side_effect=fetch):
    raise SystemExit(module.main(sys.argv[3:]))
"""
        result = subprocess.run(
            [sys.executable, "-c", code, str(SCRIPT), str(fixture), "--workspace",
             str(self.workspace.root), "collect", "--scope-id", scope_id],
            capture_output=True, text=True, check=False,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return json.loads(result.stderr)

    def greenhouse_response(self):
        return {"jobs": [{"id": 1, "title": "Operations Lead",
                           "location": {"name": "Remote US"},
                           "content": "Lead operations and improve customer workflows.",
                           "absolute_url": "https://example.test/jobs/1"}], "meta": {"total": 1}}

    def test_ten_of_840_ingests_all_rows_but_cannot_complete_search(self):
        scope = self.register()
        response = self.document("response.json", indeed_response())
        captured = self.cli("capture", "--scope-id", scope["scope_id"], "--input", str(response))
        self.assertEqual(len(captured["source_record_ids"]), 10)
        self.assertTrue(captured["intake_ids"])
        queue = json.loads((self.workspace.state / "discovery-review-queue.json").read_text())
        self.assertEqual(len(queue["items"]), 10)
        status = self.cli("status")
        self.assertFalse(status["complete"])
        self.assertEqual(status["status"], "incomplete")

    def test_missing_description_pointer_stays_pending_until_explicit_resolution(self):
        scope = self.register()
        response = self.document("pointer.json", indeed_response(1, 1, description=False))
        captured = self.cli("capture", "--scope-id", scope["scope_id"], "--input", str(response))
        self.assertTrue(captured["unresolved_pointers"])
        status = self.cli("status")
        self.assertFalse(status["complete"])
        self.assertIn("result-0", json.dumps(status["pending"]))
        record = {
            "source": "indeed", "source_record_id": "result-0",
            "employer": "Synthetic Cooperative", "title": "Operations Lead 0",
            "location": "Remote US", "posting_url": "https://example.test/jobs/0",
            "raw": {"description": "Lead customer operations and improve workflows."},
        }
        resolved = self.cli("resolve-pointer", "--scope-id", scope["scope_id"],
                            "--source-record-id", "result-0", "--input",
                            str(self.document("resolved.json", record)))
        self.assertFalse(resolved["unresolved_pointers"])
        self.assertTrue(resolved["intake_ids"])
        self.assertFalse(self.cli("status")["complete"], "Indeed still has no exhaustion contract")

    def test_bad_json_and_missing_arguments_emit_structured_errors(self):
        bad = self.root / "bad.json"
        bad.write_text("{broken", encoding="utf-8")
        self.cli("register", "--run-id", "synthetic-run", "--source", "indeed",
                 "--provider", "indeed", "--query", str(bad), success=False)
        self.cli("capture", success=False)

    def test_capture_never_invents_an_undeclared_scope(self):
        response = self.document("response.json", indeed_response(1, 1))
        self.cli("capture", "--scope-id", "retrieval:" + "0" * 64,
                 "--input", str(response), success=False)
        status = self.cli("status")
        self.assertFalse(status["complete"])
        self.assertEqual(status["status"], "unknown")
        self.assertFalse(status["scopes"])

    def test_registration_remains_pending_and_uses_actual_current_utc(self):
        before = datetime.now(timezone.utc)
        scope = self.register()
        after = datetime.now(timezone.utc)
        self.assertFalse(scope["pages"])
        self.assertEqual(scope["next_cursor"], None)
        status = self.cli("status", output=self.root / "status.json")
        self.assertFalse(status["complete"])
        self.assertIn(scope["scope_id"], json.dumps(status["pending"]))
        ledger = json.loads((self.workspace.state / "discovery-retrieval.json").read_text())
        timestamps = []

        def visit(value):
            if isinstance(value, dict):
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
            elif isinstance(value, str):
                try:
                    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    return
                if timestamp.tzinfo:
                    timestamps.append(timestamp)

        visit(ledger)
        self.assertTrue(timestamps)
        self.assertTrue(all(before <= timestamp <= after for timestamp in timestamps))

    def test_malformed_native_response_is_preserved_and_returns_failure(self):
        scope = self.register()
        response = self.document("malformed.json", {"structuredContent": {"resultsShown": 10}})
        self.cli("capture", "--scope-id", scope["scope_id"], "--input", str(response), success=False)
        status = self.cli("status")
        self.assertFalse(status["complete"])
        self.assertTrue(status["pending"])
        snapshots = list((self.workspace.sources / "discovery-retrieval").rglob("*.json"))
        self.assertTrue(snapshots, "Malformed provider responses must survive parsing failure")

    def test_explicit_failure_retains_actionable_scope(self):
        scope = self.register()
        result = self.cli("fail", "--scope-id", scope["scope_id"], "--reason", "network timeout",
                          "--next-action", "Retry the same registered source query")
        self.assertNotEqual(result["status"], "complete")
        self.assertIn("Retry the same registered source query", json.dumps(self.cli("status")))

    def test_collect_refuses_to_invent_indeed_continuation(self):
        scope = self.register()
        self.cli("collect", "--scope-id", scope["scope_id"], success=False)
        self.assertFalse(self.cli("status")["complete"])

    def test_collect_persists_first_page_and_resumes_failed_continuation(self):
        scope = self.register(provider="lever", source="public_ats",
                              query={"board": "synthetic", "employer": "Synthetic Cooperative", "page_size": 2})
        rows = [{"id": str(number), "text": f"Operations Lead {number}",
                 "categories": {"location": "Remote US", "commitment": "Full-time"},
                 "descriptionPlain": "Lead operations and improve customer workflows.",
                 "hostedUrl": f"https://jobs.lever.co/synthetic/{number}"}
                for number in (1, 2)]
        error = self.collect_with_responses(scope["scope_id"],
                                            {"None": rows, "2": {"error": "network timeout"}}, success=False)
        self.assertEqual(error["scope"]["next_cursor"], "2")
        self.assertEqual(len(error["scope"]["pages"]), 1)
        queue = json.loads((self.workspace.state / "discovery-review-queue.json").read_text())
        self.assertEqual(len(queue["items"]), 2)
        finished = self.collect_with_responses(scope["scope_id"], {"2": []})
        self.assertTrue(finished["complete"])
        self.assertEqual(len(finished["pages"]), 2)
        self.assertTrue(self.collect_with_responses(scope["scope_id"], {})["complete"])

    def test_collect_reaudits_completed_scope_and_rejects_tampered_raw(self):
        scope = self.register(provider="greenhouse", source="public_ats",
                              query={"board": "synthetic", "employer": "Synthetic Cooperative"})
        captured = self.cli("capture", "--scope-id", scope["scope_id"], "--input",
                            str(self.document("complete.json", self.greenhouse_response())))
        self.assertTrue(captured["complete"])
        (self.workspace.root / captured["pages"][0]["snapshot"]).write_text("{}", encoding="utf-8")
        error = self.collect_with_responses(scope["scope_id"], {}, success=False)
        self.assertIn("integrity", json.dumps(error))

    def test_collect_replays_interrupted_intake_before_any_network_request(self):
        scope = self.register(provider="greenhouse", source="public_ats",
                              query={"board": "synthetic", "employer": "Synthetic Cooperative"})
        response = self.document("complete.json", self.greenhouse_response())
        code = SUBPROCESS_IMPORT + """
with patch("career_pipeline.review_queue.ingest", side_effect=OSError("simulated intake interruption")):
    raise SystemExit(module.main(sys.argv[2:]))
"""
        interrupted = subprocess.run(
            [sys.executable, "-c", code, str(SCRIPT), "--workspace", str(self.workspace.root),
             "capture", "--scope-id", scope["scope_id"], "--input", str(response)],
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(interrupted.returncode, 0)
        self.assertIn("simulated intake interruption", interrupted.stderr)
        resumed = self.collect_with_responses(scope["scope_id"], {})
        self.assertTrue(resumed["complete"])
        self.assertEqual(len(resumed["pages"]), 1)
        queue = json.loads((self.workspace.state / "discovery-review-queue.json").read_text())
        self.assertEqual(len(queue["items"]), 1)

    def test_successful_retry_replaces_prior_invalid_page_without_losing_evidence(self):
        scope = self.register(provider="greenhouse", source="public_ats",
                              query={"board": "synthetic", "employer": "Synthetic Cooperative"})
        self.cli("capture", "--scope-id", scope["scope_id"], "--input",
                 str(self.document("malformed.json", {"error": "temporary provider failure"})), success=False)
        captured = self.cli("capture", "--scope-id", scope["scope_id"], "--input",
                            str(self.document("complete.json", self.greenhouse_response())))
        self.assertTrue(captured["complete"])
        self.assertEqual(len(captured["pages"]), 2)
        self.assertTrue(self.collect_with_responses(scope["scope_id"], {})["complete"])

    def test_collect_replays_interrupted_pointer_resolution_without_refetching_board(self):
        scope = self.register(provider="greenhouse", source="public_ats",
                              query={"board": "synthetic", "employer": "Synthetic Cooperative"})
        response = self.greenhouse_response()
        response["jobs"][0]["content"] = ""
        pointer_error = self.collect_with_responses(scope["scope_id"], {"None": response}, success=False)
        self.assertTrue(pointer_error["scope"]["exhausted"])
        self.assertTrue(pointer_error["scope"]["unresolved_pointers"])
        record = {"source": "public_ats", "source_record_id": "1", "employer": "Synthetic Cooperative",
                  "title": "Operations Lead", "location": "Remote US", "posting_url": "https://example.test/jobs/1",
                  "raw": {"description": "Lead operations and improve customer workflows."}}
        resolution = self.document("resolved.json", record)
        code = SUBPROCESS_IMPORT + """
with patch("career_pipeline.review_queue.ingest", side_effect=OSError("simulated pointer intake interruption")):
    raise SystemExit(module.main(sys.argv[2:]))
"""
        interrupted = subprocess.run(
            [sys.executable, "-c", code, str(SCRIPT), "--workspace", str(self.workspace.root),
             "resolve-pointer", "--scope-id", scope["scope_id"], "--source-record-id", "1", "--input", str(resolution)],
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(interrupted.returncode, 0)
        self.assertIn("simulated pointer intake interruption", interrupted.stderr)
        resumed = self.collect_with_responses(scope["scope_id"], {})
        self.assertTrue(resumed["complete"])
        self.assertFalse(resumed["unresolved_pointers"])
        queue = json.loads((self.workspace.state / "discovery-review-queue.json").read_text())
        self.assertEqual(len(queue["items"]), 1)

    def test_unstructured_native_response_preserves_extracted_rows_and_pointers(self):
        scope = self.register(provider="unstructured", source="public_web",
                              query={"search": "operations roles", "location": "Remote US"})
        original = {"content": [{"type": "text", "text":
                     "Operations Lead https://example.test/jobs/1; Transformation Lead https://example.test/jobs/2"}]}
        captured = self.cli("capture", "--scope-id", scope["scope_id"], "--input",
                            str(self.document("opaque-native.json", original)))
        self.assertFalse(captured["complete"])
        self.assertTrue(captured["pending"])
        self.assertEqual(len(captured["pages"]), 1)
        complete = {"source": "public_web", "source_record_id": "https://example.test/jobs/1",
                    "employer": "Synthetic Cooperative", "title": "Operations Lead", "location": "Remote US",
                    "posting_url": "https://example.test/jobs/1",
                    "raw": {"description": "Lead operations and improve workflows."}}
        pointer = {"source": "public_web", "source_record_id": "https://example.test/jobs/2",
                   "employer": "Synthetic Cooperative", "title": "Transformation Lead", "location": "Remote US",
                   "posting_url": "https://example.test/jobs/2", "raw": {}}
        envelope = {"raw_response": original, "extracted_listings": [complete, pointer]}
        captured = self.cli("capture", "--scope-id", scope["scope_id"], "--input",
                            str(self.document("extracted.json", envelope)))
        self.assertEqual(len(captured["pages"]), 2)
        self.assertEqual(len(captured["unresolved_pointers"]), 1)
        queue = json.loads((self.workspace.state / "discovery-review-queue.json").read_text())
        self.assertEqual(len(queue["items"]), 1)
        pointer["raw"] = {"description": "Lead transformation programs and adoption."}
        resolved = self.cli("resolve-pointer", "--scope-id", scope["scope_id"],
                            "--source-record-id", pointer["source_record_id"], "--input",
                            str(self.document("resolved.json", pointer)))
        self.assertFalse(resolved["unresolved_pointers"])
        self.assertEqual(len(resolved["source_record_ids"]), 2)
        queue = json.loads((self.workspace.state / "discovery-review-queue.json").read_text())
        self.assertEqual(len(queue["items"]), 2)
        self.assertFalse(self.cli("status")["complete"], "Extracted source records cannot prove complete native coverage")

    def test_explicit_pointer_failure_clears_after_resolution_on_supplementary_source(self):
        scope = self.register()
        self.cli("capture", "--scope-id", scope["scope_id"], "--input",
                 str(self.document("pointer.json", indeed_response(1, 840, description=False))))
        self.cli("fail", "--scope-id", scope["scope_id"], "--source-record-id", "result-0",
                 "--reason", "posting_fetch_timed_out", "--next-action", "Retry the exact official posting")
        self.assertIn("posting_fetch_timed_out", json.dumps(self.cli("status")["pending"]))
        record = {"source": "indeed", "source_record_id": "result-0", "employer": "Synthetic Cooperative",
                  "title": "Operations Lead 0", "location": "Remote US", "posting_url": "https://example.test/jobs/0",
                  "raw": {"description": "Lead operations and improve customer workflows."}}
        self.cli("resolve-pointer", "--scope-id", scope["scope_id"], "--source-record-id", "result-0",
                 "--input", str(self.document("resolved.json", record)))
        status = self.cli("status")
        self.assertFalse(status["complete"])
        self.assertFalse(status["unresolved_pointers"])
        self.assertNotIn("posting_fetch_timed_out", json.dumps(status["pending"]))
        self.assertIn("provider_has_no_pagination", json.dumps(status["pending"]))


if __name__ == "__main__":
    unittest.main()
