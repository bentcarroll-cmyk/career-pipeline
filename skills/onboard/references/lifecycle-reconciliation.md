# Lifecycle reconciliation

Offer this optional weekday workflow only when Gmail or Google Calendar is connected with the required read capability and the user opts in.

Read only job-related evidence. Update canonical local job status only for one exact `JOB-000123` match and an unambiguous application confirmation, rejection, interview invitation, or offer. Prefer employer plus requisition identity; otherwise require exact employer and role title. Read the updated `job.json` and event back before recording success.

Route contradictory, employer-generic, multi-role, or otherwise ambiguous evidence to user review without changing status. Ignore evidence whose source-scoped receipt hash was already recorded.

Persist only source kind, source-receipt hash, timestamp, event class, matched local job ID, decision, and resulting status under `Runs/lifecycle/`. Do not retain complete message or calendar bodies.

Never send or reply to email, accept an invitation, create an event, or contact another person. Those actions remain separate explicit user requests outside reconciliation.
