---
name: prepare-application
description: Use when a user explicitly asks to create, resume, verify, or export application materials for one or more local Career Pipeline job IDs.
---

# Prepare application

Create verified, versioned application packets for exact canonical local jobs.

## Trigger boundary

- Require a current explicit request such as “Prepare an application packet for JOB-000123” or a current selection from Review backlog.
- Begin work immediately in this conversation.
- Never schedule, defer to, or create a packet automation.
- A local `prepare_application` status is durable state only and does not wake Codex.
- Never submit an application or contact an employer.

## Start or resume

1. Resolve every exact `Jobs/JOB-000123/job.json`; reject missing or invalid IDs.
2. Set local status `prepare_application`, append the event, and read it back.
3. Load `State/application-manifest.json`. Start `v001`, allocate the next unused version after a completed packet, or resume the latest incomplete version.
4. If the approved profile hash changed during interrupted work, explain the conflict and ask whether to restart that job as a new version.
5. Process multiple jobs independently in the user's order so one failure cannot corrupt another packet.

## Prepare

1. Re-verify the posting and actual application destination. Preserve source evidence under the version's `working/` folder.
2. Load the approved profile, writing preferences, and role-specific instructions.
3. Read [tailoring](references/tailoring.md), derive the employer's central outcomes, and select only supported accomplishments.
4. Create a two-page resume and, unless disabled globally or for this role, a one-page cover letter using `assets/`.
5. Read [quality gates](references/quality-gates.md) and run every document and PDF check. Do not advance while any gate fails.

## Save and deliver

Place final employer-facing PDFs directly in `Applications/JOB-000123_Company_Role/vNNN/`. Keep source snapshots, drafts, extracted text, renders, and review evidence in `working/`. Then follow [local delivery and optional export](references/local-delivery-and-optional-export.md).

Resume from the latest verified manifest stage without duplicating files, versions, events, or exports.
