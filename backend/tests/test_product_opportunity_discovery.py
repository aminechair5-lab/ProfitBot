import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.main import discover_product_opportunities


class ProductOpportunityDiscoveryTests(unittest.TestCase):
    def comparison(self):
        return {
            "markets_requested": ["US", "GB", "DE", "CA"],
            "markets_scanned": [
                {"geo": "US", "count": 2, "scanned_count": 18},
                {"geo": "GB", "count": 1, "scanned_count": 16},
                {"geo": "DE", "count": 1, "scanned_count": 12},
                {"geo": "CA", "count": 0, "scanned_count": 9},
            ],
            "failures": [],
            "cross_market_count": 1,
            "items": [
                {
                    "title": "Air fryer",
                    "category": "Home & Kitchen",
                    "commercial_score": 80,
                    "confidence": "medium",
                    "source": "Google Trends Trending RSS",
                    "source_url": "https://trends.google.com/",
                    "markets": ["US", "GB", "DE"],
                    "market_count": 3,
                    "cross_market_signal": True,
                },
                {
                    "title": "Phone case",
                    "category": "Electronics",
                    "commercial_score": 90,
                    "confidence": "medium",
                    "source": "Google Trends Trending RSS",
                    "source_url": "https://trends.google.com/",
                    "markets": ["US"],
                    "market_count": 1,
                    "cross_market_signal": False,
                },
            ],
        }

    @patch("app.main.compare_trend_markets")
    def test_ranks_by_keyword_relevance_and_market_breadth(self, compare):
        compare.return_value = self.comparison()
        result = discover_product_opportunities(db=None)
        self.assertEqual(result["market_scope"], "international_only")
        self.assertEqual(result["items"][0]["title"], "Air fryer")
        self.assertEqual(result["items"][0]["market_breadth_score"], 75.0)
        self.assertEqual(result["items"][0]["discovery_priority_score"], 78.5)
        self.assertFalse(result["items"][0]["demand_verified"])
        self.assertFalse(result["items"][0]["profitability_verified"])
        self.assertEqual(result["items"][0]["rank"], 1)
        self.assertEqual(result["cross_market_count"], 1)
        self.assertEqual(result["successful_market_count"], 4)
        self.assertEqual(result["failed_market_count"], 0)
        self.assertEqual(result["rss_items_scanned_total"], 55)
        self.assertEqual(result["matched_candidates_total"], 4)

    @patch("app.main.compare_trend_markets")
    def test_minimum_market_filter(self, compare):
        compare.return_value = self.comparison()
        result = discover_product_opportunities(min_markets=2, db=None)
        self.assertEqual([x["title"] for x in result["items"]], ["Air fryer"])

    def test_rejects_invalid_minimum_markets_and_limit(self):
        with self.assertRaises(HTTPException):
            discover_product_opportunities(min_markets=0, db=None)
        with self.assertRaises(HTTPException):
            discover_product_opportunities(limit=41, db=None)


if __name__ == "__main__":
    unittest.main()
