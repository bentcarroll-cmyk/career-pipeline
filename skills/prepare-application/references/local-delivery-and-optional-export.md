# Local delivery and optional export

After every quality gate passes:

1. Verify final filenames, PDF signatures, page counts, and SHA-256 values.
2. Confirm the final PDFs sit directly in the allocated version folder and private working evidence remains under `working/`.
3. Record workspace-relative paths and exact hashes in `State/application-manifest.json`.
4. Append the version and hashes to the canonical `job.json`, set status `packet_ready`, append its event, and read all local state back.
5. Report the local application folder to the user. `packet_ready` means materials are prepared; it never means an application was submitted.

Local verification completes packet delivery. No connector is required.

If the user separately requests an optional export to Linear or another connected destination, perform it only after local completion. Export only the selected summary or exact verified final files, verify destination readback, and append a compact receipt. Do not export private drafts or full review evidence. Failure leaves the local packet ready and should report only the export retry point.

Use destination plus content hash for idempotent retry. Reuse a verified receipt rather than creating another external record or attachment.
