---
name: prepare-application
description: Use when a user explicitly asks to create, resume, verify, or export application materials for one or more local Career Pipeline job IDs.
---

# Prepare application

Create verified, versioned application packets for exact canonical local jobs. The default resume is two substantively full, readable pages using supported career evidence. A two-page count alone does not establish completion.

## Trigger boundary

- Require a current explicit request such as “Prepare an application packet for JOB-000123” or a current selection from Review backlog.
- Begin work immediately in this conversation.
- Never schedule, defer to, or create a packet automation.
- A local `prepare_application` status is durable state only and does not wake Codex.
- Never submit an application or contact an employer.

## Start or resume

1. Resolve every exact `Jobs/JOB-000123/job.json`; reject missing or invalid IDs.
2. Set local status `prepare_application` for a pre-application job and read it back. Preserve any later lifecycle status (`applied`, `interviewing`, `offer`, or `closed`) and any explicit `not_pursuing` decision; packet progress belongs in the manifest and must not rewind the canonical lifecycle.
3. Load `State/application-manifest.json`. Start `v001`, allocate the next unused version after a completed packet, or resume the latest incomplete version.
4. If the approved profile hash changed during interrupted work, explain the conflict and ask whether to restart that job as a new version.
5. Process multiple jobs independently in the user's order so one failure cannot corrupt another packet.

For a legacy packet whose original `quality_checked` receipt predates `resume_layout`, use the explicit [same-version layout recovery](references/local-delivery-and-optional-export.md#recover-a-legacy-packet-on-the-same-version). Retain the original editorial approval and PDFs. Recovery only adds current layout evidence when every original approval and artifact binding remains valid; it does not approve changed content or missing editorial work.

## Prepare

1. Re-verify the posting and actual application destination. Preserve source evidence under the version's `working/` folder.
2. Load the approved profile, writing preferences, role-specific instructions, and the full relevant canonical career sources they identify. Apply later explicit user corrections first. A condensed profile or previous resume does not replace source review.
3. Read [tailoring](references/tailoring.md). Record the central hiring outcomes, selected evidence, and a reserve of relevant omitted or compressed evidence with source references and specific disposition reasons. User-confirmed career facts are supported evidence; they need no independent third-party verification.
4. Draft the complete hiring argument at the approved readable typography and margins. Create a two-page resume and, unless disabled globally or for this role, a one-page cover letter using `assets/` as structure aids. Word counts, bullet counts, and template slots are not content ceilings.
5. Read [page completeness](references/page-completeness.md). Render, measure each page, restore relevant evidence or context, and reflow until both pages pass. More than 38.1 points of unused bottom or internal writable height blocks default resume delivery; a reviewer cannot waive it for scanability.
6. Read [quality gates](references/quality-gates.md) and run every document and PDF check against the exact final artifacts. If source review and real expansion/reflow trials expose a necessary fact that remains unresolved, ask a precise question before declaring completion; continue independent packet work while awaiting the answer.

## Save and deliver

Place final employer-facing PDFs directly in `Applications/JOB-000123_Company_Role/vNNN/`. Keep source snapshots, drafts, extracted text, renders, and review evidence in `working/`. Then follow [local delivery and optional export](references/local-delivery-and-optional-export.md).

Resume from the latest verified manifest stage without duplicating files, versions, events, or exports.
