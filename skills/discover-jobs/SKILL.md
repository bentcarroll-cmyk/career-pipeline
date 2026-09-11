---
name: discover-jobs
description: Find, verify, assess, deduplicate, and deliver qualifying current roles to the user's configured Linear project.
---

# Discover jobs

Find, verify, assess, deduplicate, and record current opportunities. This skill may run manually or from the approved discovery automation.

## Preconditions

1. Resolve the workspace from persisted configuration; never guess a path.
2. Require current approved hashes for `Career_Profile.md` and `Search_Criteria.md`.
3. Run readiness for the configured Linear workspace, team, project, labels, and write/readback actions.
4. Load `State/discovery-state.json` and create a run folder under `Runs/discovery/`.

If any precondition fails, do not advance source state or create an issue.

## Workflow

1. Search Linear for a duplicate baseline that includes archived and closed records.
2. Read [source routing](references/source-routing.md), then search only enabled sources whose required actions are currently available.
3. Save a minimal source receipt and normalize each retrieved snapshot with the matching deterministic adapter.
4. Verify the original posting and actual application destination where possible. Preserve uncertainty rather than guessing.
5. Read [evaluation and delivery](references/evaluation-and-delivery.md). Evaluate responsibilities before title, and validate every positive fit claim against an approved profile evidence ID.
6. Deduplicate by employer plus ATS/requisition identity; use the conservative employer/title/location/team fingerprint only when no stable identity exists.
7. Keep clear non-matches in local run evidence. For every new Strong Match or Worth Considering role, search Linear again immediately before creation.
8. Create the issue, read it back, and record delivery only after the destination, labels, body, and URLs match.
9. Atomically advance only successful source checkpoints and the stable review batch.

Report new matches, meaningful changes, or newly actionable failures. Stay quiet when there is no new or materially changed actionable result, including a failure already reported unchanged.
