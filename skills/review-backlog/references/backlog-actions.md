# Backlog actions

Supported actions:

- summarize Strong Match and Worth Considering canonical jobs;
- compare exact selected local IDs using responsibilities, evidence-backed fit, gaps, compensation, location, recency, and deadlines;
- surface approaching deadlines and roles needing confirmation;
- record Not pursuing or another user-directed lifecycle status locally, append its event, and read it back; and
- accept one or more exact local IDs for immediate packet preparation.

The actionable view excludes `not_pursuing` and `closed` roles. Its stable sort applies lifecycle priority first (`offer`, `interviewing`, `applied`, interrupted `prepare_application`, `packet_ready`, `needs_confirmation`, then `new`), followed by deadline urgency, confirmation need, disposition, source freshness, and job ID. A lifecycle decision therefore remains ahead of a discovery-era fit or deadline signal. Deadline urgency uses the explicit CLI `--as-of` timestamp and fixed 0, 3, 7, and 14 day windows.

`Indexes/actionable-backlog.json` is derived output. Rebuild it from canonical `Jobs/JOB-*/job.json` files instead of trusting edits to the view. A missing gap, uncertainty, re-verification timestamp, or deadline remains `null` in JSON and displays as `unknown`; never fill it from inference.

Do not create canonical jobs for roles that discovery classified as non-matches. Do not treat file or status changes as background events. Packet preparation requires a current request such as “Prepare an application packet for JOB-000123.” Preserve multi-job order and role-specific instructions, then start Prepare application without scheduling or deferring work.
