---
name: onboard
description: Use when a user asks to set up, resume, repair, or change a private Career Pipeline workspace.
---

# Onboard

Create or resume a private local-first Career Pipeline workspace through conversation.

## Boundaries

- The user-approved local workspace is the sole system of record.
- Every connector is optional, including Linear. Offer and record each choice independently.
- The plugin author receives no automatic copy and operates no collection service.
- Preserve the source resume byte-for-byte as `Sources/Resume_Original.<ext>`.
- Never copy user data into the plugin installation or repository.
- Require explicit approval of the career profile and search criteria before activation.
- Create discovery or lifecycle automations only after showing the schedule and receiving approval.
- Never schedule application-packet creation.

## Resume or start

1. Resolve the workspace only from the current conversation or persisted configuration. Never guess a path.
2. If `State/onboarding-state.json` exists, validate it and resume its recorded stage. Preserve connector declines and permission limits.
3. Otherwise offer the resumable [quick-start path](references/quick-start.md) or the full interview, then read [privacy and consent](references/privacy-and-consent.md), explain it, and obtain approval for a workspace root before creating anything.
4. Persist a receipt after every completed stage. Read back each local write or external capability test before advancing.

## Stages

### Workspace

Run the workspace initializer and validator after approval. Reject a root inside the installed plugin or source repository. Create `Profile/`, `Sources/`, `Jobs/`, `Applications/`, `Indexes/`, `Runs/`, and `State/`. Store generated paths in `State/config.json`; reusable instructions read configuration rather than embedding an absolute path.

### Connectors

Read [connector onboarding](references/connectors.md). Present every connector separately with benefit, intended access, Connect, Defer, and Skip choices, and fallback. Record `connected`, `deferred`, `declined`, or `unavailable` plus observed actions. No connector may gate the local workspace when a usable public discovery lane exists.

### Resume and interview

Copy and hash-verify the source resume without modification. Extract a draft chronology and evidence inventory into private workspace files. Use [career interview](references/interview.md). A later explicit correction overrides resume-derived text.

### Profile approval

Create `Profile/Career_Profile.md`, `Profile/Search_Criteria.md`, `Profile/Search_Criteria.json`, and `Profile/Writing_Preferences.md` from the templates in `assets/`. The JSON file must classify compensation, location, work authorization, travel, timing, role, and workplace rules as hard exclusions, preferences, or unknown-tolerant criteria. Require separate explicit user confirmation for every hard exclusion. Numeric rules use explicit comparable bounds, units, currency, and pay period; timing rules identify application deadline or required start date. Bind the JSON file to the approved readable criteria. After the user explicitly approves both representations and the readable hash is recorded in onboarding state, call `career_pipeline.criteria.approve_workspace_criteria(workspace, expected_readable_sha256=reviewed_readable_hash, expected_structured_sha256=reviewed_structured_hash)` to validate that exact reviewed snapshot under the workspace lock and atomically persist both hashes in `State/search-criteria-approval.json`. Show both criteria representations for correction. Record current hashes only after explicit approval of the career profile and search criteria. Default to a two-page resume and an enabled one-page cover letter; allow opt-out.

### Schedule and activation

Read [readiness and activation](references/readiness-and-activation.md). Offer two weekday discovery runs in the user's timezone first, then alternatives. Offer one weekday lifecycle check only when Gmail or Google Calendar is enabled; apply [lifecycle reconciliation](references/lifecycle-reconciliation.md). Keep discovery disabled until readiness passes and the user explicitly approves activation.
