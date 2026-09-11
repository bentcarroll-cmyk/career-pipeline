import unittest
from dataclasses import replace

from career_pipeline.reconciliation import (
    LifecycleCandidate,
    LifecycleEvidence,
    classify_lifecycle_evidence,
    evidence_receipt_hash,
    minimal_receipt,
)


CANDIDATE = LifecycleCandidate(
    job_id="JOB-000301",
    employer="Example Organization",
    title="Operations Lead",
    requisition_id="SYN-301",
    status="new",
)


def confirmation() -> LifecycleEvidence:
    return LifecycleEvidence(
        source_kind="gmail",
        opaque_id="synthetic-message-1",
        observed_at="2026-09-11T12:00:00Z",
        employer="Example Organization",
        role_title="Operations Lead",
        requisition_id="SYN-301",
        event_class="application_confirmation",
    )


class ReconciliationTests(unittest.TestCase):
    def test_exact_confirmation_applies_local_status_update(self) -> None:
        decision = classify_lifecycle_evidence(
            confirmation(),
            (CANDIDATE,),
            enabled_sources=("gmail",),
        )
        self.assertEqual(decision.action, "apply_update")
        self.assertEqual(decision.target_status, "applied")
        self.assertEqual(decision.job_id, "JOB-000301")

    def test_contradictory_or_generic_evidence_needs_review(self) -> None:
        contradictory = LifecycleEvidence(
            "gmail",
            "synthetic-message-2",
            "2026-09-11T12:00:00Z",
            "Example Organization",
            "Operations Lead",
            "SYN-301",
            "rejection",
            contradictory=True,
        )
        self.assertEqual(
            classify_lifecycle_evidence(
                contradictory,
                (CANDIDATE,),
                enabled_sources=("gmail",),
            ).action,
            "needs_review",
        )
        generic = LifecycleEvidence(
            "google-calendar",
            "synthetic-event-1",
            "2026-09-11T12:00:00Z",
            "Example Organization",
            None,
            None,
            "interview_invitation",
        )
        self.assertEqual(
            classify_lifecycle_evidence(
                generic,
                (CANDIDATE,),
                enabled_sources=("google-calendar",),
            ).action,
            "needs_review",
        )

    def test_seen_hash_and_disabled_source_are_ignored(self) -> None:
        evidence = confirmation()
        seen = classify_lifecycle_evidence(
            evidence,
            (CANDIDATE,),
            previously_seen=(evidence_receipt_hash(evidence),),
            enabled_sources=("gmail",),
        )
        disabled = classify_lifecycle_evidence(
            evidence,
            (CANDIDATE,),
            enabled_sources=(),
        )
        self.assertEqual(seen.reason, "evidence_already_seen")
        self.assertEqual(disabled.reason, "source_not_enabled_for_lifecycle")

    def test_terminal_or_regressive_status_change_requires_review(self) -> None:
        closed_confirmation = classify_lifecycle_evidence(
            confirmation(),
            (replace(CANDIDATE, status="closed"),),
            enabled_sources=("gmail",),
        )
        offer_rejection = classify_lifecycle_evidence(
            replace(confirmation(), event_class="rejection"),
            (replace(CANDIDATE, status="offer"),),
            enabled_sources=("gmail",),
        )

        self.assertEqual(closed_confirmation.action, "needs_review")
        self.assertEqual(closed_confirmation.reason, "status_transition_requires_review")
        self.assertEqual(offer_rejection.action, "needs_review")

    def test_minimal_receipt_excludes_matching_content(self) -> None:
        evidence = confirmation()
        decision = classify_lifecycle_evidence(
            evidence,
            (CANDIDATE,),
            enabled_sources=("gmail",),
        )
        receipt = minimal_receipt(evidence, decision)

        self.assertEqual(receipt["job_id"], "JOB-000301")
        self.assertNotIn("opaque_id", receipt)
        self.assertNotIn("employer", receipt)
        self.assertNotIn("role_title", receipt)


if __name__ == "__main__":
    unittest.main()
