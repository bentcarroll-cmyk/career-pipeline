# Changelog

## 0.1.4 — 2026-09-14 (public beta)

- Persist complete discovery intake and source descriptions in a durable review queue.
- Resume unfinished reviews and due verification retries before expanding search.
- Require individual outcomes and observed evidence for blockers; reject generic pending labels.
- Prevent unreviewed delivery and false source checkpoint advancement under the workspace lock.
- Reopen changed source content or approved inputs and retain review history without automatically suppressing title matches.
- Keep submitted applications visible in the actionable backlog when a later assessment marks the role as a non-match; preserve follow-up actions and qualification gaps without a ranking error.

## 0.1.3 — 2026-09-12 (public beta)

- Added workflow design documentation and a reproducible synthetic walkthrough.
- Updated installation, feedback, and release guidance for public repository access.
- Opened personal evaluation permissions while retaining redistribution and commercial-use restrictions.
- Preserved the existing marketplace identifier and workspace schema for beta upgrades.
- Kept runtime behavior unchanged; documented the distinction between automated verification and unmeasured user outcomes.

## 0.1.1 — 2026-09-12 (private beta)

- Prepared the first private GitHub distribution with versioned release assets.
- Added a beginner README, guided installation, runtime checks, and safe update instructions.
- Documented the macOS beta scope and reject unsupported runtime environments during preflight.
- Included private-beta usage terms, voluntary feedback forms, and an invitation guide.
- Packaged the setup, feedback, release, and license documentation with the plugin.

## 0.1.0 — 2026-09-11 (private beta)

- Added resumable, consent-based onboarding with every connector optional.
- Added canonical local `JOB-000123` folders and regenerable backlog and deduplication indexes.
- Added immediate, explicitly requested application packets with final PDFs under the local `Applications/` folder.
- Added conservative local lifecycle reconciliation and explicit optional Linear exports.
- Added backed-up schema-v2 migration, synthetic acceptance coverage, privacy scanning, and deterministic private-beta packaging.
