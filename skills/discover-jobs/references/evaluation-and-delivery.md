# Evaluation and canonical delivery

## Assessment

Resolve the current hash-bound structured criteria at the delivery boundary and verify its persisted readable and structured approval hashes. Apply only individually user-confirmed hard exclusions as deterministic filters. A missing, unparseable, unverified, conflicting, or unit-incompatible field is `unknown`, not a confirmed mismatch, and continues to semantic assessment. Numeric comparisons require typed lower and upper bounds with matching units, currency, and pay period. Timing evidence identifies application deadline or required start date; never use one as the other. Preferences and unknown-tolerant rules also continue to semantic assessment.

After hard filters pass or remain unknown, evaluate verified responsibilities before title similarity. Record role-to-profile fit, evidence-supported strengths, gaps, uncertainties, compensation evidence, geography, workplace model, travel, recency, posting status, deadline, reason codes, and a Strong Match, Worth Considering, or non-match disposition.

Never turn an unknown into a favorable assumption. A qualifying assessment requires at least one strength tied to an approved evidence ID. Keep clear non-matches in run evidence only. Rejection evidence must stay compact: stable source identity, filter/disposition result, bounded machine reason codes, a resolvable content-addressed receipt reference, and readable/structured criteria plus complete decision hashes. The referenced immutable receipt retains normalized decision evidence, source URLs, and a bounded machine rationale derived only from the decision and reason codes. Do not include full posting text, assessment prose, rationale prose, private profile text, or a canonical job ID in the run summary. A later qualifying review is the explicit promotion point and performs the normal duplicate check before allocating an ID.

## Duplicate order

1. Match normalized employer plus ATS or requisition identity.
2. When that identity is absent, use the conservative employer, exact title, location, and team fingerprint.
3. Include every canonical job status, including closed and not pursuing.
4. Treat a changed or reposted requisition as new only when stable identity or material posting evidence supports it.
5. Repeat the check against canonical folders while holding the workspace lock immediately before allocation.

## Canonical record creation

Create `Jobs/JOB-000123/` with validated `job.json`, normalized `posting.md`, evidence-backed `assessment.md`, append-only `events.jsonl`, and private `working/`. Persist relative paths. Increment the ID counter before folder creation so an interrupted allocation is never reused.

Read the complete folder back, then regenerate indexes atomically. Index failure is repairable; it never makes an index authoritative over the canonical folder.
