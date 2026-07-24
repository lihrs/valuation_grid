from datetime import datetime, timedelta
import unittest

from valuation import core


class ValuationSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.original_loaded = core._intraday_cache_loaded
        self.original_cache = core._intraday_estimation_cache

    def tearDown(self):
        core._intraday_cache_loaded = self.original_loaded
        core._intraday_estimation_cache = self.original_cache

    def test_returns_only_today_and_preserves_order(self):
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        core._intraday_cache_loaded = True
        core._intraday_estimation_cache = {
            "000001": {"date": today, "est": 1.23},
            "000002": {"date": yesterday, "est": -2.34},
            "000003": {"date": today, "est": None},
            "000004": {"date": today, "est": 0.0},
        }

        items = core.get_intraday_valuation_snapshot(
            ["000004", "000001", "000004", "000002", "000003", "999999"]
        )

        self.assertEqual([item["fund_code"] for item in items], ["000004", "000001"])
        self.assertEqual([item["estimation_change"] for item in items], [0.0, 1.23])
        self.assertTrue(all(item["_source"] == "intraday_cache" for item in items))
        self.assertTrue(all(item["_cache_date"] == today for item in items))


if __name__ == "__main__":
    unittest.main()
