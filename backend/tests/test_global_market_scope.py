import unittest

from pydantic import ValidationError

from app.schemas import ProductCreate


class InternationalMarketScopeTests(unittest.TestCase):
    def test_algeria_country_code_is_rejected(self):
        with self.assertRaises(ValidationError):
            ProductCreate(name="Test product", target_market="DZ")

    def test_algeria_name_is_rejected(self):
        with self.assertRaises(ValidationError):
            ProductCreate(name="Test product", target_market="Algeria")

    def test_algeria_in_multi_market_value_is_rejected(self):
        with self.assertRaises(ValidationError):
            ProductCreate(name="Test product", target_market="US, DZ, GB")

    def test_international_market_is_allowed(self):
        product = ProductCreate(name="Test product", target_market="US")
        self.assertEqual(product.target_market, "US")


if __name__ == "__main__":
    unittest.main()
