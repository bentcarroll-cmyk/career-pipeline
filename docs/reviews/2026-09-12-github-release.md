# Private GitHub release verification

Verified on 2026-09-12 after publication.

- Repository: https://github.com/bentcarroll-cmyk/career-pipeline
- Visibility readback: **PRIVATE**; default branch: `main`.
- GitHub Issues: enabled; wiki: disabled.
- Release: https://github.com/bentcarroll-cmyk/career-pipeline/releases/tag/v0.1.1
- Release state: published prerelease, not a draft.
- Release commit: `e346c8d5dec2b66546433a2555eed91a197e6d56`.
- Annotated tag object: `a34bad81137b168a73e701bc0d40b80d0a2dc168`, resolving to that commit.
- Plugin/Python/runtime version: `0.1.1`; workspace schema: `2`.

## Checks performed

- 265 tests passed on bundled Python 3.12.14 on macOS.
- Compilation, repository and archive plugin validation, privacy scans, and
  archive checksum passed. All 45 existing history commits were scanned before
  the first push, with zero findings from the known-pattern privacy scanner.
- The preflight rejects actual system Python 3.9.6 cleanly. Regression checks
  cover unsupported platforms, unavailable POSIX locking, missing runtime files,
  inconsistent release versions, and missing Codex command guidance.
- Independent review found no remaining release blockers after fixing platform
  requirements, version instructions, and Python cache ignore exceptions.
- All 17 relative links in the beginner and maintainer guides resolved.
- GitHub issue form YAML parsed successfully.
- No Python bytecode or cache files were tracked in the release.

## Published asset readback

`career-pipeline-plugin.zip`: 148,754 bytes, 113 archive members.

SHA-256:

```text
15b70b201aa3ee27c33493102ae0b8ebf758ee26fdb6bd54bbcebc435d27a0f1
```

The published ZIP and `.sha256` file were downloaded through authenticated
GitHub access into a fresh temporary directory. Their checksum passed. The ZIP
was byte-identical to the locally validated release.

A fresh clone at `v0.1.1` resolved to the release commit. Rebuilding from that
clone produced exactly the downloaded ZIP, and all archived members matched the
corresponding files in the clone. The downloaded, extracted package passed its
preflight, manifest validation, and privacy scan without Python site packages.
The clone's extracted-package synthetic onboarding-to-discovery-to-packet test
also passed.

This record is committed after the release; it does not change its tag or assets.

## Remaining beta observations

No friend GitHub usernames had been supplied at verification time. No repository
invitations were sent; the invitations endpoint returned zero pending invitations.
The [invitation draft and observation guide](../beta-testing.md) are ready.

A real friend's fresh Mac installation, first live shortlist, and review of real
generated PDFs remain unobserved. The tests above are synthetic package and
runtime checks, not evidence of those human workflows. Native Windows is
unsupported; Linux is unvalidated. Feedback and suggested check-ins remain
voluntary and manual.
