# Quick start

Use quick start when the user wants a usable private pipeline before completing the full career interview or optional connector setup. Persist every completed step in `State/onboarding-state.json` with `mode: quick_start`; reload that file after an interruption and resume its recorded stage.

Follow this order:

1. Explain the local privacy boundary and record explicit privacy approval.
2. Create the approved workspace and verify its standard directories and state files.
3. Copy the source resume byte-for-byte and persist its verified receipt.
4. Use the [quick-start question template](../assets/Quick_Start_Questions.template.md) to ask for at least one target-work statement and an explicit list of hard constraints. An empty list means the user confirmed that there are no hard constraints yet; never infer one.
5. Draft and obtain explicit approval for `Career_Profile.md`, `Search_Criteria.md`, and the hash-bound `Search_Criteria.json`. Record the current profile and criteria hashes.
6. Confirm packet defaults.
7. Present optional connectors by purpose. Record each as `connected`, `declined`, `deferred`, or `unavailable`. `deferred` means undecided and remains available for later setup.
8. Enable and verify at least one public discovery lane, then confirm the schedule and timezone.
9. Run persisted-state readiness checks and ask the explicit activation question.

Quick start leaves the full evidence interview and deferred connector configuration as resumable post-activation work. Record each follow-up as `pending` until completed. Activation must not erase either item or turn a deferral into a decline.
