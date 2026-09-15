# Pre-push product review — September 15, 2026

## Remediation completed

**All five findings below are fixed in the working-tree candidate.** The original
review is retained below as an audit trail; its hold verdict and code line numbers
describe the pre-fix source.

| Finding | Resulting behavior | Regression coverage |
| --- | --- | --- |
| Country-only location exclusion | Compound approved country labels remain reviewable, including punctuation and conjunction variants. Concrete nonlocal cities still exclude. Matcher version 2 reopens older automatic decisions through normal reevaluation. | `test_location_prefilter.py`, `test_review_location_prefilter.py` |
| Older replay replacing newer evidence | Older page and pointer recovery retains newer active content, decisions, delivery links, and timestamps while recording all historical capture evidence. Differing equal-time captures remain an explicit conflict until a strictly later fresh capture reopens review. | `test_retrieval.py`, `test_review_queue.py` |
| Legacy URL round-trip failure | Observations retain both snapshot and content-hash identities. URL A -> B -> A can be reviewed, including recapture of already-stuck records and later identity recovery. | `test_review_queue.py` |
| Legacy packet recovery gap | An explicit `revalidate-layout` command appends an immutable, hash-bound audit to the same version. Original quality receipts and canonical status remain intact; changed artifacts or missing approval still fail. | `test_legacy_packet_revalidation.py` |
| Identity-header misclassification | Conventional section headings stop the header scan. Wrapped titles are detected, including employer-prefixed headlines, while legitimate work history and generic capability words remain accepted. | `test_quality.py`, `test_resume_identity_check.py` |

Final verification used a fresh clean copy of the Git candidate, including all
untracked implementation and test files:

- **471 tests passed** in 38.663 seconds, up from the original 443. Each reported
  defect was exercised by a failing regression before its fix.
- Environment preflight, compilation, plugin validation, and source privacy scan
  passed. Source privacy findings: **0**.
- A fresh **127-member** release ZIP passed archive validation, privacy scanning,
  and checksum verification. ZIP privacy findings: **0**.
- ZIP SHA-256: `ef9ac732c4e826811b7b5ac5daba552ba2b13c46c607cf8996062ef2101d8201`.
- Independent follow-up reviews found no remaining actionable issue in the
  location, identity, queue/retrieval, or packet revalidation changes.

The equal-time conflict behavior was added after independent review showed that
silently preserving either version could hide a newly captured posting. Recovery
is documented in [the retrieval guide](../../skills/discover-jobs/references/retrieval.md#conflicting-captures-with-the-same-timestamp).
The layout-only packet recovery command and its limits are documented in
[the delivery guide](../../skills/prepare-application/references/local-delivery-and-optional-export.md#recover-a-legacy-packet-on-the-same-version).

These changes fix the source candidate. They do not install a plugin update,
modify private career records, commit, or push to GitHub. Live discovery,
fresh-install usability, and real editorial output retain the validation limits
stated at the end of this review.

## Initial review verdict

**Hold the push until the five confirmed defects below are fixed.** All are P2
functional defects with specific triggers. They affect which opportunities reach
review, preservation of newer evidence, or completion of application packets.

Reviewed the local version 0.1.9 working-tree candidate, including untracked source
files, on top of `c3a8a4a8c0f9503ea8fa9a78ccabe31256825973`. This is a review of
the local candidate, not a claim about the current GitHub release. Three independent
reviewers covered discovery retrieval, review queues/location filtering, and
application packets. The coordinator reproduced every finding below.

During the initial review, no implementation, canonical career records, Git state,
or remote state was changed. This review note was its only added repository file.

## 1. P2 — Country-only locations can be excluded before fit review

**Code:** `src/career_pipeline/location_prefilter.py:99-102`.

With an approved policy that retains broad locations including `United States`,
`USA`, and `US`, intake retains `United States` but automatically excludes
`United States (US)` and `USA, United States`. Those latter rows disappear from
`next_items` even though neither establishes a nonlocal city or an ineligible
location. The original captures remain stored, but the user can miss a relevant
opportunity in the actionable review queue.

The broad-location check requires a whole normalized segment to equal one approved
label, and only separates segments on semicolons, pipes, or slashes. Country names
combined with their own aliases therefore become false geographic exclusions.

**Reproduction:** Approve the existing synthetic location scope, ingest three
otherwise identical records using those three country-only labels, and call
`next_items`. Only the first record is returned.

**Fix:** Retain compound country-only labels and uncertain locations. Require
affirmative evidence of a location outside the approved area before excluding a
record; preserve the existing behavior for a clearly named nonlocal city.

## 2. P2 — Interrupted retrieval replay replaces newer evidence

**Code:** `src/career_pipeline/retrieval.py:513-515`, reaching
`src/career_pipeline/review_queue.py:199-213`.

An older captured page can survive an interrupted intake while a newer run ingests
and reviews updated content for the same posting. Replaying the old scope then
replaces the active description with the older one, moves `last_seen_at` backward,
and clears the newer review decision. History is retained, but the current queue
state is wrong. Both retrieval scopes can subsequently report complete.

**Reproduction:** Interrupt queue intake after a 10:00 capture. In a separate run,
capture changed content at 11:00 and record its review decision. Replay the original
scope at 12:00. The active content and last-seen timestamp return to 10:00, and the
decision becomes null. A synthetic salary/location change made the rollback
directly visible.

**Fix:** Persist the old capture and its intake evidence without allowing it to
supersede a newer active observation. Apply the chronology protection to ordinary
page and pointer recovery, not only normalization repairs.

## 3. P2 — Legacy URL round-trips leave review items stuck

**Code:** `src/career_pipeline/review_queue.py:166-169,210-211`.

A legacy row uses version-1 content hashes. Changing its posting URL upgrades the
current row to version 2. If that URL later returns to the original value, intake
reuses the original immutable snapshot but skips adding an observation because its
snapshot hash already exists. That existing observation still has the version-1
content hash; no observation matches the row's current version-2 hash.

`next_items` then raises `snapshot_identity_mismatch`. Recapturing the original
record again does not recover it. This can prevent normal queue review after an
upgrade and an ordinary posting URL change.

**Reproduction:** Create a single-posting legacy row using the actual base
revision's queue implementation, then use the candidate implementation to ingest
URL A -> URL B -> URL A. Verify that the active content hash has no matching
observation and that repeated `next_items` calls fail, including after recapture.

**Fix:** Preserve immutable history while adding or explicitly migrating the
versioned observation needed by the current row. Deduplication by snapshot hash
alone is insufficient when content-hash semantics change.

## 4. P2 — Older unfinished packets have no supported audit-upgrade path

**Code:** `src/career_pipeline/packets.py:983-986`; resumption promise in
`skills/prepare-application/SKILL.md:22,39`.

A legacy packet at `saved` can have a valid PDF that passes the new layout audit,
yet its original quality receipt lacks `resume_layout`. The start/resume API returns
the same version with action `resume`, but final delivery fails with
`resume_layout_missing` and `resume_layout_does_not_match_final_pdf`.

Adding the newly measured quality receipt through stage advancement fails because
stages cannot reverse. Persisting an enriched original receipt fails because
receipt history is immutable. The supported workflow therefore requires a fresh
packet version and repeated stages rather than the promised resumption.

**Reproduction:** Load a valid legacy saved packet without the new layout field.
Verify that its current PDF passes measurement. Attempt delivery, renewed quality
advancement, and receipt enrichment; all three fail for the reasons above.

**Fix:** Add an explicit, auditable upgrade or revalidation operation that records
the new final-PDF evidence without rewriting old receipts. Alternatively, identify
the required restart before returning `resume` and provide a supported recovery
flow that preserves useful existing work.

## 5. P2 — Identity checks confuse work history with the resume headline

**Code:** `src/career_pipeline/quality.py:50-64`; heading list at `:12-25`.

The identity check scans until a heading in a small exact-match list. Common
headings `PROFESSIONAL SUMMARY` and `WORK EXPERIENCE` are absent. A valid resume
with a capability-based headline can therefore be rejected when a legitimately
held work-history title matches the target opening. For example, a prior
`Staff Product Manager` role is reported as `target_role_title_in_resume_header`.

The same line-by-line parsing also misses an actual target headline wrapped across
two lines: `Senior Director, Strategy and` followed by `Operations` passes when
the target title is `Senior Director, Strategy and Operations`.

**Reproduction:** Run `validate_resume_identity_header` against those two synthetic
extracted texts. The legitimate work-history case returns a violation; the wrapped
target-headline case returns an empty error tuple.

**Fix:** Establish the actual identity-block boundary using conventional section
headings and evaluate wrapped text within that block, without scanning work history
as identity text.

## Initial review validation

- Python 3.12.14 on macOS.
- All **443 tests passed** in a clean copy of the exact Git candidate.
- The original development-folder run passed 442 tests and failed one repository
  privacy test because it scans ignored personal workspaces and browser logs.
  The Git candidate itself had zero scanner findings; no private files were removed
  and no scanner rules were weakened.
- Environment preflight, plugin validation, and `git diff --check` passed.
- A fresh 127-member release ZIP built successfully and passed archive validation,
  privacy scanning, and SHA-256 verification.
- Existing candidate file contents were checked against the clean test snapshot;
  none changed during the review.
- The additional synthetic reproductions confirmed all five defects despite the
  passing existing suite. They are not yet regression tests or fixes.

Fresh-install usability on another person's Mac, a complete live discovery run,
and editorial quality of real application materials remain outside this review.
The passing suite and package checks do not establish those outcomes.
