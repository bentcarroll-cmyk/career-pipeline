# Career Pipeline private-beta installation

Career Pipeline is a local-first Codex Desktop plugin. Its user workspace is the sole system of record; the plugin package does not contain user data and sends no telemetry.

## Verify and install

1. Keep `career-pipeline-plugin.zip` and its `.sha256` file together. From that directory, verify the package:

   ```bash
   shasum -a 256 -c career-pipeline-plugin.zip.sha256
   ```

2. Extract the ZIP into a new local directory. Do not place a Career Pipeline user workspace inside that directory.
3. Register the extracted directory as a local marketplace:

   ```bash
   codex plugin marketplace add <absolute-path-to-extracted-directory>
   ```

4. Install the plugin:

   ```bash
   codex plugin add career-pipeline@career-pipeline-private-beta
   ```

5. Start a new Codex task and ask: `Set up my job search.` New tasks pick up newly installed plugin skills.

The packet verifier ships inside the plugin and does not rely on Python packages from the host. It structurally validates final PDFs with classic cross-reference tables and a directly readable catalog and page tree. Encrypted PDFs, cross-reference streams, and compressed object streams fail closed; regenerate those files with a standard PDF export before marking a packet ready.

## Packaged private-beta smoke check

Before distributing a private-beta build, run this offline smoke check from a clean source checkout. It creates only temporary synthetic data and does not install the plugin, contact a connector, or write to an external service.

```bash
python3 -m unittest tests.unit.test_packaging.PackagingTests.test_extracted_package_completes_synthetic_local_journey -v
```

The check builds a deterministic archive, verifies its generated checksum, extracts it into a temporary directory, and runs the extracted runtime with `python -S`. It completes the real quick-start transitions and readiness gate, delivers a synthetic public discovery result, builds the actionable backlog, creates a packet with a structurally valid two-page PDF, verifies the final local artifact receipt, and diagnoses every persisted document created by the journey.

For a release candidate, also run the full test suite and these package checks:

```bash
python3 scripts/package_plugin.py --output dist
python3 scripts/validate_plugin.py dist/career-pipeline-plugin.zip
python3 scripts/scan_private_data.py dist/career-pipeline-plugin.zip
cd dist && shasum -a 256 -c career-pipeline-plugin.zip.sha256
```

## Local data and consent boundaries

During onboarding, choose a workspace outside the plugin directory. Every connector is optional, including Linear. Public ATS sources can support activation when all connectors are declined.

The selected workspace owns all durable state. Each role lives under `Jobs/JOB-000123/`; disposable views live under `Indexes/`. Final PDFs are directly browseable under `Applications/<job-and-role>/vNNN/`. Source résumés, profiles, job records, drafts, packets, and receipts remain in that workspace.

Application packets begin only after an explicit current request and are created immediately. Scheduled discovery or lifecycle checks never prepare packets. Career Pipeline does not submit applications, send messages, accept invitations, or create calendar events.

Linear is available only as an explicit optional export. A failed or unavailable export never changes the local job, packet, ID, or status.

## Updating

Keep the user workspace separate and do not delete it when updating the plugin. Verify and extract the new package, then follow [the private-beta upgrade procedure](private-beta-upgrades.md) for any workspace schema change before reinstalling the plugin. Backed-up migrations never contact connectors and preserve source documents, canonical jobs, event history, and application versions.
