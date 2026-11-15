import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Product, Supplier, SupplierOffer
from app.main import discover_product_opportunities, opportunity_supplier_readiness


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
        self.assertNotIn("DZ", result["items"][0]["markets"])
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

    def test_supplier_readiness_requires_exact_link_and_recent_verified_offer(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            product = Product(name="Air fryer", supplier_cost=20, shipping_cost=5)
            supplier = Supplier(name="Verified supplier", country_code="US",
                                verification_status="verified", reliability_score=80)
            db.add_all([product, supplier])
            db.flush()
            offer = SupplierOffer(
                supplier_id=supplier.id, product_id=product.id, product_title="Air fryer",
                source_url="https://supplier.example/air-fryer", supplier_sku="AF-001",
                unit_price=20, currency="USD", shipping_cost=5, shipping_currency="USD",
                destination_markets="US,GB", shipping_days_min=5, shipping_days_max=9,
                stock_status="in_stock", verification_status="verified",
                checked_at=datetime.now(timezone.utc),
            )
            db.add(offer)
            db.commit()

            result = opportunity_supplier_readiness(db, "Air fryer", ["US", "GB", "DZ"])
            self.assertEqual(result["status"], "verified_for_all_candidate_markets")
            self.assertEqual(result["verified_markets"], ["GB", "US"])
            self.assertNotIn("DZ", result["verified_markets"])
            self.assertEqual(len(result["offers"]), 2)

    def test_unlinked_candidate_is_not_created_automatically(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            result = opportunity_supplier_readiness(db, "New product", ["US", "GB"])
            self.assertEqual(result["status"], "no_linked_product")
            self.assertIsNone(result["linked_product_id"])
            self.assertEqual(result["missing_markets"], ["GB", "US"])

    def test_verified_offer_from_algerian_supplier_is_rejected(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            product = Product(name="Air fryer", supplier_cost=20, shipping_cost=5)
            supplier = Supplier(name="Legacy DZ supplier", country_code="DZ",
                                verification_status="verified", reliability_score=90)
            db.add_all([product, supplier])
            db.flush()
            db.add(SupplierOffer(
                supplier_id=supplier.id, product_id=product.id, product_title="Air fryer",
                source_url="https://supplier.example/air-fryer", supplier_sku="AF-DZ",
                unit_price=20, currency="USD", shipping_cost=5, shipping_currency="USD",
                destination_markets="US", shipping_days_min=5, shipping_days_max=9,
                stock_status="in_stock", verification_status="verified",
                checked_at=datetime.now(timezone.utc),
            ))
            db.commit()

            result = opportunity_supplier_readiness(db, "Air fryer", ["US"])
            self.assertEqual(result["status"], "no_current_verified_offer")
            self.assertEqual(result["verified_markets"], [])
            self.assertEqual(result["missing_markets"], ["US"])

    def test_rejects_invalid_minimum_markets_and_limit(self):
        with self.assertRaises(HTTPException):
            discover_product_opportunities(min_markets=0, db=None)
        with self.assertRaises(HTTPException):
            discover_product_opportunities(limit=41, db=None)


if __name__ == "__main__":
    unittest.main()
