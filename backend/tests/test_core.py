import unittest
from types import SimpleNamespace

from pydantic import ValidationError
from app.main import score_values
from app.db import normalize_database_url
from app.schemas import ProductCreate, ApprovalCreate, ApprovalDecision


class ProductScoringTests(unittest.TestCase):
    def test_profitable_candidate_score(self):
        product = SimpleNamespace(
            selling_price=100, supplier_cost=30, shipping_cost=5, other_costs=5,
            platform_fee_pct=5, payment_fee_pct=3, returns_reserve_pct=2,
            demand_score=80, competition_score=30, supplier_reliability=80,
            shipping_score=70, marketing_fit=90,
        )
        score, eligible, net, margin = score_values(product)
        self.assertEqual(net, 50.0)
        self.assertEqual(margin, 50.0)
        self.assertEqual(score, 71.0)
        self.assertTrue(eligible)

    def test_zero_selling_price_is_never_eligible(self):
        product = SimpleNamespace(
            selling_price=0, supplier_cost=0, shipping_cost=0, other_costs=0,
            platform_fee_pct=0, payment_fee_pct=0, returns_reserve_pct=0,
            demand_score=100, competition_score=0, supplier_reliability=100,
            shipping_score=100, marketing_fit=100,
        )
        score, eligible, net, margin = score_values(product)
        self.assertFalse(eligible)
        self.assertEqual(net, 0)
        self.assertEqual(margin, 0)


class DatabaseConfigurationTests(unittest.TestCase):
    def test_legacy_postgres_url_is_normalized(self):
        self.assertEqual(normalize_database_url("postgres://user:pass@host/db"), "postgresql://user:pass@host/db")

    def test_modern_postgres_url_is_unchanged(self):
        url = "postgresql://user:pass@host/db"
        self.assertEqual(normalize_database_url(url), url)


class RequestSchemaTests(unittest.TestCase):
    def test_product_defaults_are_safe(self):
        product = ProductCreate(name="Sample item")
        self.assertEqual(product.target_market, "Global - validate per country")
        self.assertEqual(product.supplier_cost, 0)

    def test_product_rejects_negative_cost(self):
        with self.assertRaises(ValidationError):
            ProductCreate(name="Sample item", supplier_cost=-1)

    def test_approval_requires_supported_action(self):
        with self.assertRaises(ValidationError):
            ApprovalCreate(action_type="execute_everything", description="Unsupported action")

    def test_decision_is_limited_to_approve_or_reject(self):
        with self.assertRaises(ValidationError):
            ApprovalDecision(decision="execute")


if __name__ == "__main__":
    unittest.main()
