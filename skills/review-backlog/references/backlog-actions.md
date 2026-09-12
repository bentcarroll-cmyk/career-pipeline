# Backlog actions

Supported actions:

- summarize Strong Match and Worth Considering canonical jobs;
- compare exact selected local IDs using responsibilities, evidence-backed fit, gaps, compensation, location, recency, and deadlines;
- surface approaching deadlines and roles needing confirmation;
- record Not pursuing or another user-directed lifecycle status locally, append its event, and read it back; and
- accept one or more exact local IDs for immediate packet preparation.

The actionable view excludes `not_pursuing` and `closed` roles. Its stable sort applies canonical lifecycle priority first (`offer`, `interviewing`, `applied`, `prepare_application`, `packet_ready`, `needs_confirmation`, then `new`), followed by incomplete packet work, deadline urgency, confirmation need, disposition, source freshness, and job ID. A lifecycle decision therefore remains ahead of packet, discovery-era fit, or deadline signals. Validate `State/application-manifest.json` against the canonical job IDs and packet paths before using its latest incomplete version; it may add a packet follow-up but never replace canonical status. Bind its file hash into the generated view source hash.

Deadline urgency uses the explicit CLI `--as-of` instant and fixed 3, 7, and 14 day windows. Compare timestamp deadlines as complete timezone-aware instants. Treat a date-only deadline as available through that UTC calendar date, then overdue on the following date. For an overdue discovery-stage role, recommend verifying that it remains open instead of advising action before an expired deadline.

`Indexes/actionable-backlog.json` is derived output. Rebuild it from canonical `Jobs/JOB-*/job.json` files instead of trusting edits to the view. A missing gap, uncertainty, re-verification timestamp, or deadline remains `null` in JSON and displays as `unknown`; never fill it from inference.

Do not create canonical jobs for roles that discovery classified as non-matches. Do not treat file or status changes as background events. Packet preparation requires a current request such as “Prepare an application packet for JOB-000123.” Preserve multi-job order and role-specific instructions, then start Prepare application without scheduling or deferring work.
