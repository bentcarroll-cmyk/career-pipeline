# Offline demo

This walkthrough uses the repository's existing **synthetic fixtures and automated tests**. Employers, career evidence, messages, documents, and export responses are fictional. It requires no accounts, API keys, web access, or real résumé.

Run from the repository root on macOS with Python 3.11 or newer. The helpers use the Python standard library. Use a suitable interpreter in place of `python3` if needed.

## 1. Preview the local workspace

```sh
python3 scripts/init_workspace.py --root /tmp/career-pipeline-synthetic-demo --dry-run
```

Expected: a directory plan including `Profile`, `Sources`, `Jobs`, `Applications`, `Indexes`, `Runs`, and `State`. This command creates no workspace. Canonical job folders preserve the records while indexes provide rebuildable views.

## 2. Check a synthetic onboarding state

```sh
python3 scripts/check_readiness.py --fixture tests/fixtures/synthetic/onboarding/ready.json
```

Expected:

```json
{"ready": true, "failure_codes": []}
```

The helper creates and removes a temporary workspace with a synthetic source résumé and approved profile hashes. Readiness here validates fixture configuration and local evidence; it does not connect to an employer source.

## 3. Run the workflow demonstration

```sh
python3 -m unittest \
  tests.e2e.test_local_discovery \
  tests.e2e.test_immediate_packets \
  tests.e2e.test_private_beta -v
```

Expected: **4 tests pass**. The [journey test](../tests/e2e/test_private_beta.py) checks these behaviors:

1. Onboarding activates with optional connectors declined.
2. Reviewed fixtures produce two saved roles, one duplicate, and one non-match.
3. Explicit packet requests start work, resume interrupted stages, and preserve another version.
4. Synthetic application confirmation updates status; ambiguous evidence needs review.
5. A mismatched export readback is rejected; verified readback records an export.
6. Missing or corrupt indexes rebuild from canonical records.

The tests clean up their temporary workspaces. Export and lifecycle inputs are simulated locally; no messages are read or sent and no external records are created. Minimal generated PDFs and asserted quality receipts exercise state transitions, not real authoring or visual review.

## 4. Check failure boundaries

```sh
python3 -m unittest \
  tests.unit.test_criteria \
  tests.integration.test_discovery_integrity \
  tests.integration.test_packet_resumption \
  tests.integration.test_index_regeneration \
  tests.unit.test_automation_policy -v
```

Expected: **47 tests pass**. These tests check that unknown compensation remains unknown, stale assessment hashes fail before mutation, changed packet inputs require a new version, and packet scheduling is rejected.

All four commands were verified on macOS on September 12, 2026, using the Codex-provided Python runtime. The two test commands passed **51 tests total**. These are selected demo checks, not a claim of full product acceptance. For broader repository validation:

```sh
python3 -m unittest discover -s tests -t . -v
```

The [design document](design.md) explains the architecture and tradeoffs behind these behaviors. Actual research quality, résumé quality, usability, and application outcomes require separate evaluation.
