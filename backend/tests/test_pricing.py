import unittest
from datetime import date, timedelta
from decimal import Decimal

from backend.kupp.config import load_thresholds
from backend.kupp.pricing import price_drop_vs_history, unit_price

THRESHOLDS = load_thresholds()
AS_OF = date(2026, 11, 15)


def daily_prices(prices):
    start = AS_OF - timedelta(days=len(prices) - 1)
    return [
        {"observed_at": (start + timedelta(days=i)).isoformat(), "price_minor": price, "is_promo": None}
        for i, price in enumerate(prices)
    ]


class PriceLogicTests(unittest.TestCase):
    def classify(self, observations, current):
        return price_drop_vs_history(
            observations,
            current,
            percentile=THRESHOLDS["regular_price_percentile"],
            min_observations=THRESHOLDS["minimum_price_observations"],
            min_days=THRESHOLDS["minimum_price_distinct_days"],
            window_days=THRESHOLDS["history_window_days"],
            min_drop_percent=THRESHOLDS["minimum_price_drop_percent"],
            as_of=AS_OF,
        )

    def test_unit_price_per_kg_and_litre(self):
        self.assertEqual(unit_price(2590, 450, "g"), ("kg", Decimal("57.55555555555555555555555556")))
        self.assertEqual(unit_price(1990, 330, "ml"), ("l", Decimal("60.30303030303030303030303030")))

    def test_half_time_promotion_is_price_drop_against_75th_percentile(self):
        observations = daily_prices([7000] * 30 + [10000] * 30)
        result = self.classify(observations, 7000)
        self.assertEqual(result["regular_price_minor"], Decimal("10000"))
        self.assertEqual(result["status"], "price drop vs history")
        self.assertTrue(result["is_price_drop"])
        self.assertEqual(result["price_drop_percent"], Decimal("30"))

    def test_flat_price_product_has_no_price_drop(self):
        result = self.classify(daily_prices([10000] * 30), 10000)
        self.assertEqual(result["regular_price_minor"], Decimal("10000"))
        self.assertEqual(result["status"], "no price drop")
        self.assertFalse(result["is_price_drop"])

    def test_too_little_history_is_insufficient_data(self):
        result = self.classify(daily_prices([10000] * 5), 5000)
        self.assertEqual(result["status"], "insufficient data")
        self.assertIsNone(result["regular_price_minor"])
        self.assertFalse(result["is_price_drop"])


if __name__ == "__main__":
    unittest.main()