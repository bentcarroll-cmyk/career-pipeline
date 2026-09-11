---
name: onboard
description: Set up or resume a private Career Pipeline workspace, including required Linear readiness and individually optional connectors.
---

# Onboard

Create or resume a private Career Pipeline workspace through conversation. Start this workflow for “Set up my job search” and setup-resumption requests.

## Non-negotiable boundaries

- User data lives in the user-approved local workspace and the user's own connected services.
- The plugin author receives no automatic copy and operates no collection service.
- Linear is required. Treat every other connector as an independent, optional decision.
- Never display, copy into the plugin repository, or log more personal content than the current step requires.
- Preserve the source resume byte-for-byte as `Sources/Resume_Original.<ext>`.
- Never activate discovery from resume-only defaults. Require explicit approval of the generated career profile and search criteria.
- Create automations only after showing the final schedule and receiving explicit approval.
- Never schedule application-packet creation.

## Resume or start

1. Locate the user-approved workspace only from the current conversation or persisted configuration. Do not guess a path.
2. If `State/onboarding-state.json` exists, validate it and resume at its recorded stage. Respect saved connector declines and permissions.
3. Otherwise read [privacy and consent](references/privacy-and-consent.md), explain it, and ask the user to approve a workspace root before creating directories.
4. Persist a receipt after every completed stage using the deterministic state helpers. Do not mark a stage complete until its external write or capability check has been read back.

## Stages

### Workspace

After approval, run the workspace initializer and validator. Reject a root inside the installed plugin or its source repository. Store generated paths in `State/config.json`; reusable instructions must read those values.

### Linear and optional connectors

Read [connector onboarding](references/connectors.md). Connect Linear to an existing workspace and team, then create and verify the standard Job Search project, labels, and views. Offer optional connectors one at a time. Record `connected`, `declined`, or `unavailable` plus the actions actually observed.

### Resume and interview

Copy the original resume without modification and verify its hash. Extract a draft chronology and evidence inventory into private working files. Then use [career interview](references/interview.md). Treat user corrections as authoritative over resume-derived assumptions.

### Profile approval

Create the three documents from the templates in `assets/`:

- `Profile/Career_Profile.md`
- `Profile/Search_Criteria.md`
- `Profile/Writing_Preferences.md`

Show the documents for correction. Record current hashes only after the user explicitly approves both the career profile and search criteria. Default packet settings to a two-page resume and an enabled one-page cover letter; allow the cover letter to be disabled globally.

### Schedule and activation

Read [readiness and activation](references/readiness-and-activation.md). Offer twice each weekday in the user's timezone first, then daily, weekly, or custom. Offer one weekday lifecycle check only when Gmail or Calendar is enabled. Run readiness, show actionable failures, and keep discovery disabled until readiness passes and the user explicitly approves activation.
