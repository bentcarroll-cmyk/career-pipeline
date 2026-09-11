---
name: prepare-application
description: Immediately prepare and verify application packets for exact Linear tickets explicitly selected by the user.
---

# Prepare application

Immediately create and deliver a tailored packet for one or more exact Linear tickets explicitly selected by the user.

## Trigger boundary

- Require a current request such as “Prepare an application packet for JOB-123” or an explicit selection passed by Review backlog.
- A manually added `Prepare application` label is durable state only; it does not wake Codex.
- Never create, request, or defer to a scheduled packet automation.
- Begin work in this conversation. Never submit the application or contact the employer.

## Start or resume

1. Resolve every exact ticket and verify it belongs to the configured Job Search project.
2. Add `Prepare application` and read the label back.
3. Load `State/application-manifest.json`. Start `v001`, allocate a later unused version after a delivered packet, or resume the latest incomplete version.
4. If the approved profile hash changed since an interrupted draft, explain the conflict and ask whether to restart that ticket as a new version.
5. Process multiple tickets independently in the user's order so one failure does not corrupt another packet.

## Prepare

1. Re-verify the original posting and actual application destination. Preserve a snapshot or receipt under the version's `working/` folder.
2. Load the current approved career profile, writing preferences, and role-specific instructions.
3. Read [tailoring](references/tailoring.md), derive the employer's central hiring outcomes, and select only supported accomplishments.
4. Create a two-page resume and, unless disabled globally or for this role, a one-page cover letter using the templates in `assets/`.
5. Read [quality gates](references/quality-gates.md) and run every gate with Codex document and PDF capabilities. Do not advance while any gate fails.

## Save and deliver

Place the exact final PDFs directly in the allocated version folder; keep source snapshots, drafts, extracted text, renders, and review evidence in `working/`. Hash final bytes, then follow [Linear delivery](references/linear-delivery.md).

Resume from the latest verified manifest stage without duplicating files, versions, attachments, comments, or labels.
