# Local delivery and optional export

After every quality gate passes:

1. Verify final filenames, PDF signatures, page counts, and SHA-256 values. Run the deterministic layout audit on the actual final resume again and require its exact result to match the quality receipt's `resume_layout` evidence, or the bound supplemental audit for a recovered legacy packet. Final delivery rejects missing, stale, or failing measurements, including packets that previously reached `quality_checked` under older code. Reviewer explanations and all-true quality flags cannot override this check.
2. Confirm the final PDFs sit directly in the allocated version folder and private working evidence remains under `working/`.
3. Record workspace-relative paths and exact hashes in `State/application-manifest.json`.
4. Append the version and hashes to the canonical `job.json`, append its event, and read all local state back. Set status `packet_ready` only from a pre-application status; otherwise preserve the existing lifecycle status.
5. Report the local application folder and a concise verification summary, including two full resume pages and the measured gaps for both pages. If a necessary evidence question remains, report the incomplete version and exact unresolved fact instead of calling it ready. `packet_ready` means materials are prepared; it never means an application was submitted.

Local verification completes packet delivery. No connector is required.

## Recover a legacy packet on the same version

A packet created before the layout audit may already be `quality_checked`, `saved`, `local_verified`, or `ready`, with no `resume_layout` field in its original quality receipt. Do not edit that receipt or restart merely to add the missing audit. First use the normal start/resume checks to confirm the current approved inputs still match the packet, and confirm its retained editorial review still applies to the unchanged final documents. The recovery command validates the preserved input, posting, draft, and final-PDF hash bindings; it does not refresh the posting or independently compare current profile, criteria, or preferences files. An unbound or incomplete historical approval cannot be upgraded this way.

Run from the plugin root using the bundled PDF Python runtime, or a Python environment with the `pdf` dependency group installed. Supply the exact job ID, the operator performing this audit, and the current timestamp:

```text
python3 scripts/update_packet.py --workspace "/full/path/to/My Job Search" --job-id JOB-000123 --stage revalidate-layout --reviewer "Reviewing operator" --occurred-at "<current ISO 8601 timestamp with timezone>"
```

This is a layout-only check. It remeasures the actual PDFs and appends one immutable `layout_revalidated` receipt to the existing version in `State/application-manifest.json`. That receipt binds the current measurement and every artifact hash to a SHA-256 of the untouched original quality receipt. It leaves the packet stage, version, original receipts, and canonical job status unchanged. A retry rechecks the files and reuses the recorded audit, even when run at a later time.

For a recovered `saved` or `local_verified` packet, finish the existing version with the normal delivery command:

```text
python3 scripts/update_packet.py --workspace "/full/path/to/My Job Search" --job-id JOB-000123 --stage complete-local --occurred-at "<current ISO 8601 timestamp with timezone>"
```

For `quality_checked`, record the normal `saved` receipt using the original approved artifact hashes before local delivery. For `ready`, verify the existing delivery using `scripts/verify_packet_files.py`; no new version or canonical delivery is required. Normal delivery and verification independently remeasure the final PDF and require exact agreement with the supplemental audit.

Stop recovery if a gate is missing or false, an original input/review binding conflicts, any final PDF changed, or measurement fails. Keep the historical evidence intact and use an explicitly requested new version for changed documents or renewed editorial review. A modern quality receipt with a missing, failed, or stale layout result is ineligible for legacy recovery. Never remove its `resume_layout` field to make it eligible.

## Optional export

If the user separately requests an optional export to Linear or another connected destination, perform it only after local completion. Export only the selected summary or exact verified final files, verify destination readback, and append a compact receipt. Do not export private drafts or full review evidence. Failure leaves the local packet ready and should report only the export retry point.

Use destination plus content hash for idempotent retry. Reuse a verified receipt rather than creating another external record or attachment.
