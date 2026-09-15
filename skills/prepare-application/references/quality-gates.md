# Packet quality gates

All gates must pass against the exact final artifacts and produce evidence under `working/`. A checklist of `true` values is not evidence of page completeness.

1. **Factual:** every candidate claim maps to an approved profile evidence ID or an authoritative career source and passage, including explicit user confirmations. Every employer fact maps to the posting or another verified employer source. Independent third-party proof of user-confirmed career facts is unnecessary. Retain supported actions and qualitative results when an exact measurement is uncertain; preserve qualifications and contribution boundaries.
2. **Chronology:** employers, roles, dates, transitions, and ordering agree with the latest user-approved chronology.
3. **Tailoring and completeness:** the full relevant canonical sources were reviewed under the current source priority. The selected evidence and reserve address the employer's central outcomes; specific omission reasons and actual expansion/reflow trials establish that useful evidence was not cut merely to leave space. Review the weakest included item against the strongest omitted item and whether both can fit. Resolve necessary unanswered career questions before completion.
4. **ATS structure:** conventional headings, selectable text, simple reading order, no essential information in images, headers, or footers.
5. **Page space:** follow [page completeness](page-completeness.md). Measure the actual final PDF: each page's unused top/bottom height and largest internal body-text gap must be at most 38.1 points within the fixed supported geometry. No clipping, overflow, or orphaned sections. A failed, absent, or stale measurement blocks delivery regardless of a reviewer pass or Boolean flags.
6. **PDF text:** extracted text is complete, ordered, and materially matches the approved source draft.
7. **Page count:** resume is exactly two pages; enabled cover letter is exactly one.
8. **Visual:** render every page and inspect typography, spacing, alignment, artifacts, and page balance.
9. **Resume content policy:** the identity block uses a supported capability headline and does not contain the employer's exact target job title or target employer. The resume contains no requested, preferred, desired, or negotiable start date. After extracting the final resume text, run `python3 scripts/check_resume_identity.py --resume-text <extracted-resume.txt> --employer <exact-employer> --title <exact-target-title> --output <working/receipts/resume_identity.json>`. A nonzero exit blocks delivery.

Use the Codex document capability for authoring and the PDF capability for page count, extraction, rendering, and visual inspection. Load the bundled workspace dependencies for the available document/PDF runtime. If a required capability is unavailable, report the actionable dependency or measurement failure rather than marking the check complete. Outside the bundled runtime, PDF audit dependencies are available through `pip install '.[pdf]'`.

## Deterministic final-PDF audit

Run with a Python runtime containing the PDF dependencies:

```text
python3 scripts/measure_resume_layout.py --pdf <final-resume.pdf> --output <working/receipts/resume_layout.json>
```

Exit 0 means the measured layout passes; exit 1 means a quality failure; exit 2 means measurement or dependency failure. Preserve the full generated object as `resume_layout` in the structured quality receipt alongside the existing factual, chronology, tailoring, ATS, text, page-count, and visual fields. Do not manually invent or edit measurement values, artifact hashes, or the audit's pass decision.

The audit identifies its policy and schema version, exact PDF SHA-256 hash, actual page count, fixed geometry, per-page gaps, font observations, and failures. It supports portrait US Letter with 41.75-point top/bottom body boundaries and 36-point horizontal safety bounds. Body text must be at least 10 points with median body type no larger than 14 points; the first-page identity has a separate allowance. The audit supplements substantive review and cannot establish relevance or truthful attribution by itself.

Use the workspace-aware packet API at the `quality_checked` stage. It remeasures the current final PDF and compares the result with `resume_layout`; delivery repeats this check. Missing evidence, modified PDFs, changed measurements, or a failed audit cannot be bypassed with `QualityReceipt.all_passed(...)` or all-true flags. A `quality_checked` stage recorded by older code does not replace the final delivery audit.

If the original historical quality receipt has no `resume_layout` field, the [legacy recovery command](local-delivery-and-optional-export.md#recover-a-legacy-packet-on-the-same-version) can append a fresh, bound layout audit on the same version. It requires the unchanged PDFs and original complete editorial approval; it never fills in missing review gates or rewrites earlier receipts. Modern quality receipts continue to require their own valid layout evidence.

Bind the private final editorial review to the final PDF and authoring-document paths and SHA-256 hashes, posting snapshot/hash, canonical source paths/hashes, selected/omitted decisions, revision history, reviewer, and `pass` or `revise`. Any content or layout change requires a new render, measurement, and final-artifact review.

Save drafts, extracted text, every page render, source snapshots, the evidence reserve, revision history, final editorial review, the resume-identity receipt, `resume_layout.json`, and the structured quality receipt in `working/`. Final employer-facing PDFs are the only PDFs directly in the version folder.
