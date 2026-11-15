import unittest
from datetime import date, timedelta
from decimal import Decimal

from backend.kupp.config import load_thresholds
from backend.kupp.pricing import nonpromo_baseline, unit_price, verify_deal

THRESHOLDS = load_thresholds()


class PriceLogicTests(unittest.TestCase):
    def test_unit_price_per_kg_and_litre(self):
        self.assertEqual(unit_price(2590, 450, "g"), ("kg", Decimal("57.55555555555555555555555556")))
        self.assertEqual(unit_price(1990, 330, "ml"), ("l", Decimal("60.30303030303030303030303030")))

    def test_baseline_requires_fourteen_nonpromo_days(self):
        start = date(2026, 10, 1)
        observations = [
            {"observed_at": (start + timedelta(days=i)).isoformat(), "price_minor": 1000 + i, "is_promo": 0}
            for i in range(14)
        ]
        baseline = nonpromo_baseline(
            observations,
            min_observations=THRESHOLDS["minimum_nonpromo_observations"],
            min_days=THRESHOLDS["minimum_nonpromo_days"],
        )
        self.assertTrue(baseline["eligible"])
        self.assertEqual(baseline["distinct_days"], 14)
        self.assertEqual(baseline["baseline_price_minor"], Decimal("1006.5"))

    def test_unknown_promo_status_does_not_enter_baseline(self):
        observations = [
            {"observed_at": "2026-10-01", "price_minor": 1000, "is_promo": None}
            for _ in range(20)
        ]
        baseline = nonpromo_baseline(
            observations,
            min_observations=THRESHOLDS["minimum_nonpromo_observations"],
            min_days=THRESHOLDS["minimum_nonpromo_days"],
        )
        self.assertFalse(baseline["eligible"])
        self.assertEqual(baseline["observations"], 0)

    def test_verified_discount_needs_eligible_baseline_and_ten_percent_drop(self):
        observations = [
            {"observed_at": (date(2026, 10, 1) + timedelta(days=i)).isoformat(), "price_minor": 10000, "is_promo": 0}
            for i in range(14)
        ]
        baseline = nonpromo_baseline(
            observations,
            min_observations=THRESHOLDS["minimum_nonpromo_observations"],
            min_days=THRESHOLDS["minimum_nonpromo_days"],
        )
        threshold = THRESHOLDS["minimum_verified_discount_percent"]
        self.assertTrue(verify_deal(baseline, 9000, min_discount_percent=threshold)["verified"])
        self.assertFalse(verify_deal(baseline, 9500, min_discount_percent=threshold)["verified"])
        insufficient = nonpromo_baseline(
            observations[:10],
            min_observations=THRESHOLDS["minimum_nonpromo_observations"],
            min_days=THRESHOLDS["minimum_nonpromo_days"],
        )
        self.assertFalse(verify_deal(insufficient, 5000, min_discount_percent=threshold)["verified"])


if __name__ == "__main__":
    unittest.main()
