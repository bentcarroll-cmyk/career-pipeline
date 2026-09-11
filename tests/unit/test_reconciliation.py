import unittest

from career_pipeline.reconciliation import (
    LifecycleCandidate,
    LifecycleEvidence,
    classify_lifecycle_evidence,
)


CANDIDATE = LifecycleCandidate(
    ticket_id="JOB-301",
    employer="Example Organization",
    title="Operations Lead",
    requisition_id="SYN-301",
)


class ReconciliationTests(unittest.TestCase):
    def test_exact_confirmation_applies_status_update(self) -> None:
        decision = classify_lifecycle_evidence(
            LifecycleEvidence(
                source_kind="gmail",
                opaque_id="message-hash-1",
                observed_at="2026-09-11T12:00:00Z",
                employer="Example Organization",
                role_title="Operations Lead",
                requisition_id="SYN-301",
                event_class="application_confirmation",
            ),
            (CANDIDATE,),
        )
        self.assertEqual(decision.action, "apply_update")
        self.assertEqual(decision.target_status, "Applied")
        self.assertEqual(decision.ticket_id, "JOB-301")

    def test_contradictory_or_generic_evidence_needs_review(self) -> None:
        contradictory = LifecycleEvidence(
            "gmail",
            "message-hash-2",
            "2026-09-11T12:00:00Z",
            "Example Organization",
            "Operations Lead",
            "SYN-301",
            "rejection",
            contradictory=True,
        )
        self.assertEqual(
            classify_lifecycle_evidence(contradictory, (CANDIDATE,)).action,
            "needs_review",
        )
        generic = LifecycleEvidence(
            "calendar",
            "event-hash-1",
            "2026-09-11T12:00:00Z",
            "Example Organization",
            None,
            None,
            "interview_invitation",
        )
        self.assertEqual(
            classify_lifecycle_evidence(generic, (CANDIDATE,)).action,
            "needs_review",
        )

    def test_seen_evidence_is_ignored(self) -> None:
        evidence = LifecycleEvidence(
            "gmail",
            "message-hash-3",
            "2026-09-11T12:00:00Z",
            "Example Organization",
            "Operations Lead",
            "SYN-301",
            "offer",
        )
        decision = classify_lifecycle_evidence(
            evidence,
            (CANDIDATE,),
            previously_seen=("message-hash-3",),
        )
        self.assertEqual(decision.action, "ignore")


if __name__ == "__main__":
    unittest.main()
