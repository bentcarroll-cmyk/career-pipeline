import unittest

from career_pipeline.checkpoints import DiscoveryState
from career_pipeline.linear_delivery import DeliveryReceipt, record_delivery
from career_pipeline.reporting import discovery_report


class DiscoveryDeliveryTests(unittest.TestCase):
    def test_verified_delivery_is_recorded_once(self) -> None:
        state = DiscoveryState()
        receipt = DeliveryReceipt(
            candidate_key="req:example:syn-1",
            issue_id="SYN-701",
            verified=True,
            body_hash="a" * 64,
        )
        once = record_delivery(state, receipt)
        twice = record_delivery(once, receipt)
        self.assertEqual(once, twice)
        self.assertEqual(once.deliveries["req:example:syn-1"], "SYN-701")

    def test_quiet_report_suppresses_unchanged_failures(self) -> None:
        self.assertIsNone(discovery_report((), (), (), ()))
        self.assertIsNone(
            discovery_report((), (), ("indeed_unavailable",), ("indeed_unavailable",))
        )
        report = discovery_report(
            ("SYN-701",), (), ("browser_expired",), ("indeed_unavailable",)
        )
        self.assertIn("SYN-701", report)
        self.assertIn("browser_expired", report)


if __name__ == "__main__":
    unittest.main()
