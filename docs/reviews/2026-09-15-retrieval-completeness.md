# Discovery retrieval completeness repair

## Outcome and boundaries

Discovery now distinguishes reviewing captured jobs from retrieving the declared source scope. Indeed's native connector cap is not removable by this repository; Indeed evidence remains explicitly supplementary even when every returned job has been reviewed. Supported complete-board collection covers Greenhouse and Ashby, with resumable offset pagination for Lever. This establishes accounting within declared scopes, not internet-wide coverage.

Every known query and board must be registered before requests. Native responses are saved intact before parsing and review intake. Missing descriptions, unattempted scopes, malformed responses, interruptions, and source limitations remain visible. Unsupported responses have a durable unstructured capture/extraction path rather than being silently omitted or treated as an empty source.

The checkpoint guard reconciles provider exhaustion, raw evidence, every registered scope, exact intake receipts, and individual reviews. Saved completion flags and hand-written success claims are insufficient. Older partial captures cannot be retroactively certified by the new code.

## Smaller batches without lost coverage

The discovery instructions now require approved hard constraints with safe provider semantics, focused responsibility/geography queries, and smaller review batches after complete capture. Unknown compensation and other uncertain criteria remain reviewable. Narrower child searches never erase a capped parent's unresolved coverage.

## Regression and independent review coverage

- Ten returned out of a larger advertised total cannot advance a source checkpoint.
- Registering nine scopes but capturing only eight remains incomplete.
- Full Lever pages require continuation; partial requests retain captured pages and the next offset.
- Raw capture precedes parsing and intake; interrupted pages and pointer resolutions replay before new network requests.
- Missing descriptions retain exact job identity and cannot be resolved by substituting another opening.
- Malformed captures followed by empty retries cannot erase identifiable jobs or unknown malformed rows.
- Tampered snapshots, missing receipts, duplicate source entries, omitted enabled sources, and stale scopes fail closed.
- Combined review/retrieval summaries use one workspace lock; differing source completion timestamps are order-independent.
- Independent reviewers checked provider contracts, CLI instructions, and core completion/recovery behavior. Findings were reproduced with regression tests before fixes.

## Final validation

- All 130 focused retrieval, provider-parser, collector, checkpoint, review-queue, delivery, end-to-end flow, and CLI tests passed against an isolated source snapshot. The CLI subset contains 15 subprocess tests.
- The final independent recovery review approved the changes with no remaining important findings; six targeted lifecycle regressions passed, including supplementary/nonterminal pointer failures and independent page/pointer recovery.
- Compilation, plugin manifest/ZIP structure validation, the built ZIP privacy scan, and the discovery-scoped whitespace check passed. The privacy scanner was not weakened.
- Full-suite result on the same source snapshot: 384 tests, 381 passed, two failures and one error in separate application/PDF-packaging work present in the shared checkout. Remaining cases were `test_valid_later_stage_and_explicit_legacy_selected_manifest_are_accepted`, `test_archive_pdf_verifier_runs_without_site_packages`, and `test_extracted_package_completes_synthetic_local_journey`. Those modules and their in-progress changes were not altered for this repair.
- The clean validation copy excluded existing private user workspaces and browser logs that caused the original repository-wide privacy scan failure. Neither private data nor scanner policy was changed. Archive privacy validation used the real packaging rules.

Focused command (Python 3.11 or newer):

```sh
PYTHONPATH=src python3 -m unittest tests.unit.test_retrieval tests.unit.test_checkpoints tests.unit.test_review_queue tests.unit.test_source_pages tests.unit.test_collectors tests.integration.test_discovery_delivery tests.integration.test_retrieval_flow tests.integration.test_retrieval_cli -q
```

## Deployment and historical data

This task changes source code, tests, and operator instructions only. It does not install the changes, refresh saved schedules, repair the previous discovery run, initiate a new job search, submit applications, or reset canonical records. Installation must load the updated discovery skill and saved automation prompts before relying on these guards. Any historical recovery needs original response provenance or a newly authorized search.

See the [retrieval workflow](../../skills/discover-jobs/references/retrieval.md) and [upgrade guidance](../private-beta-upgrades.md).
