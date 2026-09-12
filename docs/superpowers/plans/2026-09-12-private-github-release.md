# Private GitHub Release Implementation Plan

**Goal:** Publish Career Pipeline privately with a versioned beta release and a
usable invitation, setup, feedback, and update path for friends.

**Architecture:** Preserve the existing local-authoritative workspace and runtime.
Distribute allowlisted runtime files and guides through a private repository
marketplace and a GitHub prerelease. The user's explicit request authorizes
repository creation, release publication, and the previously recommended work.

**Tech stack:** Python standard library, Codex plugin marketplace, Git, GitHub CLI.

**Spec:** `../specs/2026-09-11-career-pipeline-design.md`, especially sections 15–16,
plus the approved private-repository and friend-sharing recommendations.

## Implementation

- [x] Add README, guided ZIP and Git installation, runtime requirements, and safe
  update instructions in the beginner documentation.
- [x] Add a private-beta LICENSE, voluntary feedback forms, an invitation draft,
  and a first-friend observation guide. Do not send invitations without names.
- [x] Extend the deterministic archive allowlist to include these guides and terms.
- [x] Add a read-only environment preflight with clear unsupported-Python errors;
  cover its meaningful failure modes and the packaged documentation contract.
- [x] Release version 0.1.1 consistently in the manifest and Python metadata.
- [x] Review the diff and run the full suite, compilation, plugin validation,
  privacy scans, package checks, and checksum verification.
- [ ] Inspect tracked source and history before the initial push; create the
  private personal repository, push main and the release tag, and publish assets.
- [ ] Read back privacy, branch/tag identity, prerelease assets, and downloaded
  checksum; verify the published tag through a fresh clone and synthetic journey.
- [ ] Report remaining real-friend installation and feedback observation plainly.

## Ownership

Documentation worker owns README and beginner installation/update guides.
Packaging worker owns packaging, environment preflight, and focused tests.
Coordinator owns terms, feedback, release docs/metadata, integration checks,
repository publication, and final readback. No career data enters the repository.
