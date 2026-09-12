# Update the private beta

Keep your **plugin installation** and **private job-search workspace** separate. Updating the plugin replaces reusable instructions and helpers. Your résumé, profile, saved jobs, history, and application versions belong in the workspace you chose during onboarding.

The plugin version and workspace schema version are different. Release **v0.1.1** uses workspace **schema 2**, as v0.1.0 did. A workspace already on schema 2 does not need a schema migration just to install v0.1.1.

## Before updating

1. Finish any active Career Pipeline work. Pause its discovery or lifecycle schedules while updating so they cannot write to the workspace during the change.
2. Note your private workspace location and make a backup of that entire folder. Keep it private and outside the plugin installation. The migration helper's state backup is not a full backup of your résumé and application files.
3. Read the new release's notes and [changelog](../CHANGELOG.md). Download and extract a new release into a separate plugin folder; keep your previous plugin folder until the update is verified.
4. Follow the [installation guide](private-beta-installation.md) to verify the new ZIP checksum and run the environment and package checks before changing the installed plugin.

## Recommended: ask Codex to update it

Paste this into a Codex task with access to the new extracted plugin, replacing the bracketed paths:

```text
Update my Career Pipeline plugin using this release.

New extracted plugin folder: [full path to the new plugin folder]
Download folder containing the ZIP and .sha256 file: [full path to the download folder]
Existing private workspace: [full path to my existing job-search workspace]

Read docs/private-beta-installation.md and docs/private-beta-upgrades.md in the
new plugin folder. Verify the ZIP checksum and run the environment and package
checks using Python 3.11+ before installing. Inspect the existing plugin and
marketplace registration, and preserve my private workspace and its backup.

Remove the installed career-pipeline plugin, replace the existing
career-pipeline-private-beta marketplace registration with this extracted
folder, and reinstall career-pipeline@career-pipeline-private-beta using the
available Codex runtime. Do not register a duplicate marketplace or initialize
a replacement workspace. Read back the installed version and source.

If my workspace needs a schema migration, show its dry-run plan and backup
location before asking me to approve that exact migration. After installation,
tell me to start a new task and resume my existing workspace. Verify the saved
jobs and application versions before restoring any previously approved schedules.
```

## Terminal fallback: replace the marketplace registration

Use a Codex executable with plugin support. First remove the installed plugin and the old marketplace registration:

```bash
codex plugin remove career-pipeline@career-pipeline-private-beta
codex plugin marketplace remove career-pipeline-private-beta
```

For a downloaded ZIP, register the **new extracted plugin root**, then reinstall:

```bash
codex plugin marketplace add "/full/path/to/New Career Pipeline Plugin"
codex plugin add career-pipeline@career-pipeline-private-beta
```

For a GitHub installation, use the desired release tag instead of a local path. These commands install v0.1.1; substitute the exact published tag for a later release:

```bash
codex plugin marketplace add bentcarroll-cmyk/career-pipeline --ref v0.1.1
codex plugin add career-pipeline@career-pipeline-private-beta
```

Choose one route. Local and GitHub installs share the name `career-pipeline-private-beta`. Adding a second source with that name can collide with the existing registration. Removing and re-adding the registration also lets you change a GitHub source's pinned release tag. GitHub installs continue to require authenticated Git access to this private repository.

These commands manage the plugin and marketplace, not the separately chosen workspace. Do not delete or replace the workspace while changing installation sources. If reinstallation fails, keep the workspace intact and use the [feedback guide](beta-testing.md) to report the failure.

## Resume and check your existing work

Start a **new Codex task** so it loads the updated skills. Say:

> Resume my existing Career Pipeline workspace at [full workspace path]. Verify the installed version and workspace health, then show my saved jobs and application versions.

Confirm that your profile, saved jobs, statuses, and application versions are present. Resume your previously approved schedules only after these checks pass. A healthy installation is not evidence that a scheduled run or connector has succeeded; check those separately when you use them.

## Only when a workspace migration is needed

Run migration commands from the new plugin root, using Python 3.11 or newer. First produce a read-only plan:

```bash
python3 scripts/migrate_workspace.py --workspace "/full/path/to/My Job Search"
```

Review the listed changes and backup location. To approve that exact plan, repeat the command with the displayed confirmation token:

```bash
python3 scripts/migrate_workspace.py --workspace "/full/path/to/My Job Search" --confirm "token-from-the-plan"
```

The schema 1 to schema 2 migration moves Linear settings into optional connector settings and adds canonical `Jobs/` and regenerable `Indexes/` paths. It does not import or change external records. Importing an older external backlog is a separate decision.

Applying an approved plan first creates and verifies a state backup under `State/backups/`, updates configuration atomically, and rebuilds disposable indexes. Source documents, existing job folders, event history, and application versions are preserved. If migration fails after changing state, the helper attempts to restore the original state and reports the outcome. Do not continue if rollback also fails; retain the backup and report the error without sharing private files.

Downgrading a plugin is not a workspace rollback. If a release changes the workspace schema, check compatibility before opening that workspace with an older plugin. Keep the full pre-update workspace backup until you have verified the update.
