# Readiness and activation

Run readiness after profile approval and schedule selection. A passing report requires:

- the standard local directories and state files are writable;
- the source resume receipt is valid;
- the career profile and search criteria hashes match the explicitly approved files;
- packet defaults specify a two-page resume and zero-or-one-page cover letter;
- the timezone and discovery cadence are valid;
- Linear workspace, team, project, labels, views, issue actions, comments, and attachments are verified;
- every connector has a saved decision and observed capabilities;
- at least one enabled discovery lane is usable.

Show failures with concrete remediation and rerun only the failed checks. Do not infer approval from file existence.

When ready, show the selected schedule and ask one explicit activation question. Only after approval may the Codex automation tool create:

1. discovery, using the rendered discovery prompt; and
2. optional lifecycle reconciliation when Gmail or Calendar is connected and the user opted in.

Read each created automation back before persisting its identifier. Profile approval by itself is not automation approval. There is no application-packet automation; packet work starts only from an explicit current user request.
