# Private-beta workspace upgrades

Career Pipeline updates never overwrite source resumes, canonical job folders, event history, or application versions.

Before changing workspace state, the migration helper produces a dry-run plan with a confirmation token. Applying that exact token creates a backup under `State/backups/`, updates configuration atomically, and rebuilds disposable indexes from `Jobs/`. A failed migration restores the original state files.

The schema 1 to schema 2 migration changes Linear from a required destination into optional connector settings and adds canonical `Jobs/` and regenerable `Indexes/` paths. It does not contact Linear, import issues, archive issues, or delete external records. Copying an old external backlog into local folders is a separate explicit user decision.

Run the plan first:

```bash
python3 scripts/migrate_workspace.py --workspace <approved-root>
```

Review the listed changes and backup location. Apply only by repeating the command with the displayed token:

```bash
python3 scripts/migrate_workspace.py --workspace <approved-root> --confirm <token>
```
