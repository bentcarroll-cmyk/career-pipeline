---
name: review-backlog
description: Use when a user asks to summarize, compare, filter, or update opportunities already recorded by Career Pipeline.
---

# Review backlog

Help the user understand and manage the canonical local opportunity backlog. Read [backlog actions](references/backlog-actions.md) before changing state.

## Workflow

1. Resolve the configured workspace and validate or regenerate `Indexes/backlog.json` from canonical `Jobs/` folders.
2. Summarize new roles, compare exact local job IDs using stored assessment evidence, or surface deadlines without reclassifying from title alone.
3. For an explicit not-pursuing or lifecycle decision, update the exact `job.json`, append an event, read both back, and regenerate affected indexes.
4. When the user explicitly selects one or more exact local job IDs for materials, validate every canonical folder, preserve order and per-role instructions, and invoke Prepare application immediately in the same conversation.

A local `prepare_application` status records durable progress but does not wake Codex. Never claim an application was submitted and never send employer-facing communication.
