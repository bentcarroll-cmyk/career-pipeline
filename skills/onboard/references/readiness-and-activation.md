# Readiness and activation

Run readiness after profile approval and schedule selection. A passing report requires:

- the standard local directories and state files are writable;
- the workspace lock, atomic read/write probe, next-ID state, canonical job scan, and index regeneration succeed;
- the source resume receipt is valid;
- approved profile and criteria hashes match the current files, and the profile contains at least one stable `EV-*` evidence identifier;
- packet defaults specify a two-page resume and zero-or-one-page cover letter;
- timezone and discovery cadence are valid;
- every connector has a saved connected, declined, deferred, or unavailable decision and truthful observed capabilities; and
- at least one enabled public or connected discovery lane is usable.

No connector is required. Show failures with concrete remediation and rerun only failed checks. Do not infer approval from file existence.

When ready, show the selected schedule and ask one explicit activation question. Only after approval may the automation tool create:

1. discovery, using the rendered discovery prompt; and
2. optional lifecycle reconciliation when Gmail or Google Calendar is enabled and the user opted in.

Read each created automation back before persisting its identifier. Profile approval is not automation approval. Application packets have no automation; they begin only from a current explicit request.

For a quick start, keep the full career interview and deferred connector configuration recorded as pending after activation. Resume either without disabling discovery or changing the user's existing connector decisions.
