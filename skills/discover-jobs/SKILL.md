---
name: discover-jobs
description: Use when a user or approved discovery schedule asks to find, verify, assess, deduplicate, or record current job opportunities.
---

# Discover jobs

Find and assess current opportunities, then persist qualifying roles in canonical local folders.

## Preconditions

1. Resolve the workspace from persisted configuration. Never guess a path.
2. Require current approved hashes for `Profile/Career_Profile.md` and `Profile/Search_Criteria.md`. When `Profile/Search_Criteria.json` exists, validate its readable binding and `State/search-criteria-approval.json` at the delivery boundary. Existing workspaces without the structured file remain usable until their criteria are next revised.
3. Run local readiness and ensure at least one configured discovery lane is usable.
4. Load `State/discovery-state.json`, inspect retrieval and review status, validate or rebuild `Indexes/` from `Jobs/`, and create run evidence under `Runs/discovery/`.

If a precondition fails, do not advance source state or allocate a job ID.

## Workflow

1. Read [source routing](references/source-routing.md), [accounted source retrieval](references/retrieval.md), and [complete intake and resumable review](references/review-queue.md). Search only enabled sources with currently observed required actions.
   Register the full currently known query and board plan before the first request, including planned probes; register any later-discovered query before executing it. Capture the entire native response immediately through `discovery_retrieval.py`; use its supported board collectors to follow all pages and `unstructured` scopes for other enabled sources. Resume actionable retrieval and review work before unrelated expansion. A recorded permanent provider limitation permits related narrower queries or independent complete board scopes once returned rows and actionable work are handled; preserve the original incomplete scope. Persist every returned listing and missing-description pointer before selecting positives. Every unique review item needs an individual outcome; genuine blockers need observed attempts and a retry. Check canonical and configured legacy/email history before final delivery.
2. Save a content-addressed minimal source receipt and normalize criterion evidence into typed, source-bound values. Numeric values require explicit bounds and comparable units; conflicting, malformed, unverified, or ambiguous values remain unknown.
3. Verify the original posting and actual application destination where possible. Preserve uncertainty.
4. Read [evaluation and canonical delivery](references/evaluation-and-delivery.md). Apply user-confirmed deterministic hard filters before semantic assessment. Evaluate responsibilities before title and validate positive fit claims against approved profile evidence IDs.
5. Deduplicate against canonical folders: employer plus ATS or requisition identity first, otherwise the conservative employer, title, location, and team fingerprint.
6. Keep hard-filter rejections and clear semantic non-matches in compact run evidence without allocating IDs. Include stable identity, bounded machine reason codes, a confined content-addressed evidence-receipt reference, and assessment/readable/structured criteria hashes. Preserve source URLs and a bounded machine rationale derived only from the decision and reason codes in the referenced immutable receipt; never copy full postings, assessment prose, rationale prose, or private profile text into the run summary.
7. For each novel Strong Match or Worth Considering role, acquire the workspace lock, repeat the duplicate check, allocate the next local ID, and create the complete `Jobs/JOB-000123/` folder.
8. Read `job.json` and required evidence files back before success. Regenerate `Indexes/backlog.json` and `Indexes/deduplication.json` from canonical folders.
9. Advance only successful source checkpoints backed by exact `coverage_scope_ids` and reconciled intake receipts, then save the stable batch of new local IDs.
   Report retrieval scope coverage separately from reviewed, blocked, and untouched listings. A complete review batch does not establish a complete search. Missing retrieval evidence, capped Indeed results, omitted queries, unfinished pages, and unresolved pointers remain incomplete even when every ingested row is reviewed. Persist and report every qualifying role with explicit uncertainties.

Report new matches, meaningful changes, or newly actionable failures. Stay quiet when nothing materially changed, including a failure already reported unchanged. Connector export is outside this workflow and requires a separate explicit request.
