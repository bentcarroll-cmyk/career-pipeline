# Install Career Pipeline

This guide is for people evaluating the public beta using Codex Desktop on macOS. The recommended path is a release ZIP and guided setup in Codex. It does not require Git command-line authentication or a `pip` installation.

The filenames and marketplace identifier retain `private-beta` for compatibility with existing installations. They do not indicate that repository access is restricted. This project is for personal use and evaluation under its [license](../LICENSE).

## Before you begin

- Download from [the public repository](https://github.com/bentcarroll-cmyk/career-pipeline). No repository invitation or GitHub sign-in is needed to view it or download the release assets.
- Have Codex Desktop installed and signed in on **macOS**, with plugin support available. Local package checks have been validated on macOS; installation on a new tester's Mac remains part of beta testing. **Native Windows is unsupported** by the current workspace locking, and **Linux has not been validated**.
- The local helpers require **Python 3.11 or newer**. Your computer's `python3` may be older; Codex can check for a suitable runtime it provides. No extra Python packages are needed for the core helpers.
- Job discovery needs an available web capability. Final application packets also need Codex document and PDF capabilities. Connectors such as Linear, Gmail, and Google Drive are optional.

The guided path has package checks and a synthetic local workflow test. A complete installation and real job search on a new tester's computer remain part of beta testing.

## Recommended: download a release and ask Codex to install it

1. Open [Releases](https://github.com/bentcarroll-cmyk/career-pipeline/releases). Download both `career-pipeline-plugin.zip` and `career-pipeline-plugin.zip.sha256` from the newest release's **Assets**. Use those files, rather than GitHub's automatic “Source code” downloads. The public beta release is [v0.1.3](https://github.com/bentcarroll-cmyk/career-pipeline/releases/tag/v0.1.3).
2. Keep the ZIP and checksum together, and extract the ZIP into a new folder. Choose a stable location you will keep, such as a `Career Pipeline Plugin` folder inside Documents. The plugin root is the folder containing `README.md`, `scripts/`, and `skills/`.
3. In Codex, open a task with access to that extracted folder. Paste the prompt below, replacing the two bracketed paths with your actual folders. Codex may ask for access needed to read the download or install the plugin.

```text
Install this Career Pipeline public beta for me.

Extracted plugin folder: [full path to the extracted plugin folder]
Download folder containing the ZIP and its .sha256 file: [full path to the download folder]

Read docs/private-beta-installation.md in the extracted plugin folder first.
Verify the release ZIP checksum before installing. Use an available Python 3.11+
runtime, including Codex's provided runtime if appropriate, to run
scripts/check_environment.py and scripts/validate_plugin.py on the extracted
plugin. The core helpers do not need pip packages.

Inspect the available Codex plugin commands and existing marketplaces. If
career-pipeline-private-beta is already registered, follow the upgrade guide
instead of creating a duplicate. Register this extracted folder as the local
marketplace and install career-pipeline@career-pipeline-private-beta using
the available Codex runtime. Read back the installed plugin and version.

Keep my job-search workspace separate from the plugin folder. After the
installation succeeds, tell me to start a new task with “Set up my job search.”
If a required runtime or plugin command is unavailable, explain the specific
missing requirement and the next step without claiming installation succeeded.
```

4. After Codex confirms installation, start a **new task** and say **“Set up my job search.”** Newly installed skills are picked up in new tasks.
5. During onboarding, choose a separate private workspace for your résumé, profile, saved jobs, and application files. Review your career profile and search criteria before approving them. You can defer or skip connectors and leave schedules disabled.

Guided setup means Codex performs the checks and supported installation commands with you. It is not a promise that every Codex version or computer has an identical installation interface.

## Terminal fallback: install the downloaded ZIP

Use this path if you prefer commands. `codex` must resolve to a Codex executable with plugin support. Check its help if your installed version differs. In the examples, `python3` means a verified Python 3.11+ executable; substitute its full path when needed.

From the download directory, verify the ZIP:

```bash
shasum -a 256 -c career-pipeline-plugin.zip.sha256
```

Continue only if it reports `career-pipeline-plugin.zip: OK`. If it fails, download both files again from the same release. A matching checksum confirms the ZIP matches the supplied checksum; it does not replace checking that you downloaded from the intended repository.

From the extracted plugin root, run the preflight and manifest check:

```bash
python3 scripts/check_environment.py
python3 scripts/validate_plugin.py
```

The preflight is read-only. It checks the platform's required locking support, Python version, and package runtime, versions, and identifiers. A passing check on Linux does not mean that environment has been validated for this beta. It can report that the Codex command is unavailable on your shell path even when Codex Desktop provides it; use the guided path to locate the available runtime. It does not test your account, GitHub permissions, connectors, or the entire desktop installation flow.

Register and install, replacing the example path with the extracted plugin root:

```bash
codex plugin marketplace add "/full/path/to/Career Pipeline Plugin"
codex plugin add career-pipeline@career-pipeline-private-beta
```

If the marketplace already exists, follow the [upgrade guide](private-beta-upgrades.md). Keep the extracted folder available, then start a new Codex task with **“Set up my job search.”**

## Alternative: install from the public GitHub repository

This route reads the public repository and does not require a repository invitation or Git credentials. Codex itself must still be installed and signed in. If the GitHub route is unavailable in your Codex version, use the release ZIP route above.

For the public beta release:

```bash
codex plugin marketplace add bentcarroll-cmyk/career-pipeline --ref v0.1.3
codex plugin add career-pipeline@career-pipeline-private-beta
```

The marketplace is pinned to that release tag. For a later version, use the exact tag from its release and follow the [upgrade guide](private-beta-upgrades.md). Both install routes use the same marketplace identity, so do not register both at once.

## Your workspace and application files

Your selected workspace holds the durable records. Saved roles live under `Jobs/JOB-000123/`; final PDFs are directly accessible under `Applications/<job-and-role>/vNNN/`. The plugin installation contains reusable instructions and helpers, and must stay separate from those private files.

Career Pipeline has no hosted collection service or telemetry. Codex and any connected services still process the information used in their requests under their respective settings and terms. The plugin author receives no automatic copy. Feedback is voluntary and manually shared.

Packet preparation starts only when you explicitly request it. The default packet is a two-page résumé and an enabled one-page cover letter; you can opt out of the cover letter. Documents must pass factual, text, page-count, and visual checks before being marked ready. If Codex's document or PDF capability is unavailable, preparation stops with the missing requirement. The bundled structural PDF verifier needs no extra Python packages, but supports only directly readable catalogs/page trees and classic cross-reference tables; unsupported PDF structures must be regenerated using a standard PDF export.

Career Pipeline does not submit applications, send employer messages, accept invitations, or create calendar events. Optional Linear exports require a separate request, and failed exports do not change your local records.

## Help and updates

If a step fails, save its message and the plugin version, then follow [the beta feedback guide](beta-testing.md). Remove personal details before sharing. Use [the upgrade guide](private-beta-upgrades.md) for later releases; preserve your private workspace when replacing the plugin.

Maintainer build and distribution checks are in [the release guide](releasing.md).
