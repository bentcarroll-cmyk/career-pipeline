---
name: discover-jobs
description: Use when a user or approved discovery schedule asks to find, verify, assess, deduplicate, or record current job opportunities.
---

# Discover jobs

Find and assess current opportunities, then persist qualifying roles in canonical local folders.

## Preconditions

1. Resolve the workspace from persisted configuration. Never guess a path.
2. Require current approved hashes for `Profile/Career_Profile.md` and `Profile/Search_Criteria.md`.
3. Run local readiness and ensure at least one configured discovery lane is usable.
4. Load `State/discovery-state.json`, validate or rebuild `Indexes/` from `Jobs/`, and create run evidence under `Runs/discovery/`.

If a precondition fails, do not advance source state or allocate a job ID.

## Workflow

1. Read [source routing](references/source-routing.md). Search only enabled sources with currently observed required actions.
2. Save a minimal source receipt and normalize each retrieved snapshot with its deterministic adapter.
3. Verify the original posting and actual application destination where possible. Preserve uncertainty.
4. Read [evaluation and canonical delivery](references/evaluation-and-delivery.md). Evaluate responsibilities before title and validate positive fit claims against approved profile evidence IDs.
5. Deduplicate against canonical folders: employer plus ATS or requisition identity first, otherwise the conservative employer, title, location, and team fingerprint.
6. Keep clear non-matches in run evidence without allocating IDs.
7. For each novel Strong Match or Worth Considering role, acquire the workspace lock, repeat the duplicate check, allocate the next local ID, and create the complete `Jobs/JOB-000123/` folder.
8. Read `job.json` and required evidence files back before success. Regenerate `Indexes/backlog.json` and `Indexes/deduplication.json` from canonical folders.
9. Advance only successful source checkpoints and save the stable batch of new local IDs.

Report new matches, meaningful changes, or newly actionable failures. Stay quiet when nothing materially changed, including a failure already reported unchanged. Connector export is outside this workflow and requires a separate explicit request.
