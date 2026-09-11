import unittest

from career_pipeline.backlog import SelectionError, selection_from_request


class ReviewBacklogTests(unittest.TestCase):
    def test_explicit_multi_ticket_selection_preserves_order(self) -> None:
        selection = selection_from_request(
            ("JOB-102", "JOB-101", "JOB-102"),
            {"JOB-101": "Emphasize fictional operations evidence."},
            explicit_request=True,
        )
        self.assertEqual(selection.ticket_ids, ("JOB-102", "JOB-101"))
        self.assertIn("JOB-101", selection.per_role_instructions)

    def test_label_state_without_request_cannot_trigger_packet(self) -> None:
        with self.assertRaises(SelectionError):
            selection_from_request(
                ("JOB-101",),
                {},
                explicit_request=False,
            )


if __name__ == "__main__":
    unittest.main()
