# Maintaining private-beta releases

The repository is `bentcarroll-cmyk/career-pipeline`. Keep its visibility private.
Publish releases from `main` with an immutable version tag, and mark beta releases
as prereleases. The manifest, `pyproject.toml`, and `src/career_pipeline/__init__.py`
must carry the same version.
Release v0.1.1 is the first GitHub distribution of the local beta.

## Validate the candidate

This beta is validated on macOS. Native Windows is unsupported because the
runtime uses POSIX file locking and directory synchronization; Linux is unvalidated.
Use Python 3.11 or newer. If the shell's `python3` is older, use the Python
executable provided by Codex's workspace dependencies. Substitute that executable
for `python3` in every command below. No third-party packages are needed for the
plugin's core checks.

From the repository root:

```bash
python3 scripts/check_environment.py
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src scripts
python3 scripts/validate_plugin.py .
python3 scripts/scan_private_data.py .
python3 scripts/package_plugin.py --output dist
python3 scripts/validate_plugin.py dist/career-pipeline-plugin.zip
python3 scripts/scan_private_data.py dist/career-pipeline-plugin.zip
```

Then, from `dist/`:

```bash
shasum -a 256 -c career-pipeline-plugin.zip.sha256
```

The full suite includes a deterministic archive comparison and the extracted
package's synthetic onboarding-to-discovery-to-packet journey without site
packages. It does not test live job-source coverage, real document writing, or a
friend's graphical installation. Keep those limits in release notes.

Review the intended commit and the archived member list. The archive includes
runtime files, beginner guides, and license terms. It excludes the Git history,
tests, generated workspaces, and application documents. Before the first push,
also inspect the tracked source and history for private material. A scanner is a
check for known patterns, not proof that every sensitive fact has been detected.

## Publish and read back

1. Update all three version fields, the changelog, and release-specific guide links.
2. Review and commit the candidate. Push it to the private repository's `main`.
3. Create a matching version tag at that exact commit and push the tag.
4. Create a GitHub prerelease from that tag with the ZIP and SHA-256 file.
   Include what's changed, requirements, setup links, and validation limits.
5. Read back repository visibility, default branch, remote commit and tag,
   release status, and asset names. Download the published assets to a fresh
   temporary directory and verify their checksum and byte equality.
6. Clone the published tag into a fresh temporary directory, validate its
   marketplace and package, and rerun the extracted synthetic package journey.

Use the [releases page](https://github.com/bentcarroll-cmyk/career-pipeline/releases)
in evergreen invitations because GitHub's "latest release" shortcut may skip
prereleases. Keep each published release's files immutable; corrections get a
new version.

## Access and feedback

Invite only usernames explicitly supplied by the owner. Repository invitations
grant repository access; they do not share a person's local career workspace.
Confirm the effective collaborator permissions before inviting testers. Personal
GitHub repositories may give collaborators write access; do not promise read-only
roles without verifying that the repository's account type supports them.

Use the private issue forms and [beta testing guide](beta-testing.md) for feedback.
Ask the first friend to complete the observed setup before expanding the group.
Keep proposed check-ins and invitation drafts distinct from messages actually sent.
