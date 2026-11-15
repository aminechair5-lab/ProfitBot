import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import main


class TrendMarketComparisonTests(unittest.TestCase):
    def test_rejects_algeria_as_target_market(self):
        with self.assertRaises(HTTPException) as caught:
            main.compare_trend_markets(markets="US,DZ", db=None)
        self.assertEqual(caught.exception.status_code, 400)

    def test_limits_scan_to_four_markets(self):
        with self.assertRaises(HTTPException) as caught:
            main.compare_trend_markets(markets="US,GB,DE,FR,CA", db=None)
        self.assertEqual(caught.exception.status_code, 400)

    def test_rejects_invalid_market_code(self):
        with self.assertRaises(HTTPException) as caught:
            main.compare_trend_markets(markets="US,USA", db=None)
        self.assertEqual(caught.exception.status_code, 400)

    def test_groups_same_candidate_across_markets(self):
        candidate = {
            "title": "Air fryer deals",
            "category": "Home & Kitchen",
            "commercial_score": 75,
            "confidence": "medium",
            "source": "Google Trends Trending RSS",
            "url": "https://trends.google.com/example",
        }
        response = {
            "count": 1,
            "scanned_count": 20,
            "items": [candidate],
        }
        with patch.object(main, "google_trend_signals", return_value=response):
            result = main.compare_trend_markets(markets="US,GB", db=None)
        self.assertEqual(result["cross_market_count"], 1)
        self.assertEqual(result["items"][0]["markets"], ["US", "GB"])
        self.assertTrue(result["items"][0]["cross_market_signal"])
        self.assertIn("not demand or sales", result["items"][0]["score_interpretation"])


if __name__ == "__main__":
    unittest.main()
