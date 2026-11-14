import unittest
from types import SimpleNamespace

from pydantic import ValidationError
from app.main import score_values
from app.db import normalize_database_url
from app.schemas import ProductCreate, ApprovalCreate, ApprovalDecision
from app.trends import classify_trend_title


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
        self.assertEqual(normalize_database_url("postgres://user:pass@host/db"), "postgresql+psycopg://user:pass@host/db")

    def test_modern_postgres_url_is_normalized(self):
        url = "postgresql://user:pass@host/db"
        self.assertEqual(normalize_database_url(url), "postgresql+psycopg://user:pass@host/db")


class RequestSchemaTests(unittest.TestCase):
    def test_product_defaults_are_safe(self):
        product = ProductCreate(name="Sample item")
        self.assertEqual(product.target_market, "Global - validate per country")
        self.assertEqual(product.supplier_cost, 0)

    def test_product_name_is_trimmed(self):
        product = ProductCreate(name="  Sample item  ")
        self.assertEqual(product.name, "Sample item")

    def test_product_rejects_blank_name(self):
        with self.assertRaises(ValidationError):
            ProductCreate(name="   ")

    def test_product_rejects_negative_cost(self):
        with self.assertRaises(ValidationError):
            ProductCreate(name="Sample item", supplier_cost=-1)

    def test_product_rejects_non_finite_cost(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    ProductCreate(name="Sample item", supplier_cost=value)

    def test_product_rejects_non_http_source_url(self):
        for value in ("javascript:alert(1)", "file:///etc/passwd", "not-a-url"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    ProductCreate(name="Sample item", source_url=value)

    def test_product_rejects_embedded_url_credentials(self):
        with self.assertRaises(ValidationError):
            ProductCreate(name="Sample item", source_url="https://user:password@example.com/item")

    def test_product_accepts_http_source_url(self):
        product = ProductCreate(name="Sample item", source_url="https://example.com/item")
        self.assertEqual(product.source_url, "https://example.com/item")

    def test_product_rejects_oversized_database_fields(self):
        with self.assertRaises(ValidationError):
            ProductCreate(name="Sample item", category="x" * 101)
        with self.assertRaises(ValidationError):
            ProductCreate(name="Sample item", target_market="x" * 101)

    def test_approval_requires_supported_action(self):
        with self.assertRaises(ValidationError):
            ApprovalCreate(action_type="execute_everything", description="Unsupported action")

    def test_approval_rejects_non_finite_amount(self):
        with self.assertRaises(ValidationError):
            ApprovalCreate(action_type="payment", description="Test payment", amount=float("inf"))

    def test_approval_currency_must_be_uppercase_code(self):
        with self.assertRaises(ValidationError):
            ApprovalCreate(action_type="payment", description="Test payment", currency="usd")

    def test_decision_is_limited_to_approve_or_reject(self):
        with self.assertRaises(ValidationError):
            ApprovalDecision(decision="execute")


class MultilingualTrendClassificationTests(unittest.TestCase):
    def test_english_multiword_product_phrase(self):
        result = classify_trend_title("best air fryer price")
        self.assertIsNotNone(result)
        self.assertEqual(result["category"], "Home & Kitchen")
        self.assertIn("air fryer", result["matched_product_terms"])
        self.assertGreaterEqual(result["commercial_score"], 65)

    def test_arabic_product_and_shopping_intent(self):
        result = classify_trend_title("أفضل قلاية هوائية سعر")
        self.assertIsNotNone(result)
        self.assertEqual(result["category"], "Home & Kitchen")
        self.assertIn("قلاية هوائية", result["matched_product_terms"])
        self.assertIn("أفضل", result["shopping_intent_terms"])

    def test_french_product_and_shopping_intent(self):
        result = classify_trend_title("meilleur prix cafetière")
        self.assertIsNotNone(result)
        self.assertEqual(result["category"], "Home & Kitchen")
        self.assertIn("cafetière", result["matched_product_terms"])
        self.assertIn("prix", result["shopping_intent_terms"])

    def test_non_commercial_topic_is_excluded(self):
        self.assertIsNone(classify_trend_title("مباراة كرة القدم اليوم"))
        self.assertIsNone(classify_trend_title("football match result"))

    def test_product_phrase_inside_longer_text_is_matched(self):
        result = classify_trend_title("où acheter un aspirateur robot")
        self.assertIsNotNone(result)
        self.assertEqual(result["category"], "Home & Kitchen")


if __name__ == "__main__":
    unittest.main()
