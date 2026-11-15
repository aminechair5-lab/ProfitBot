import unittest
from types import SimpleNamespace

from app.main import eligibility_reasons


def product(**overrides):
    values = {
        "target_market": "US",
        "selling_price": 100,
        "supplier_name": "Verified Supplier",
        "source_url": "https://example.com/product",
        "supplier_reliability": 80,
        "shipping_score": 80,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ProductEligibilityReasonTests(unittest.TestCase):
    def test_eligible_product_has_no_blockers(self):
        self.assertEqual(eligibility_reasons(product(), 85, 30, 30), [])

    def test_reports_all_missing_publication_requirements(self):
        reasons = eligibility_reasons(
            product(target_market="DZ", selling_price=0, supplier_name="", source_url="",
                    supplier_reliability=20, shipping_score=10),
            40, -5, -5,
        )
        self.assertEqual(len(reasons), 9)
        self.assertTrue(any("الجزائري" in reason for reason in reasons))
        self.assertTrue(any("المورد" in reason for reason in reasons))
        self.assertTrue(any("رابط" in reason for reason in reasons))
        self.assertTrue(any("الربح" in reason for reason in reasons))
        self.assertTrue(any("الهامش" in reason for reason in reasons))
        self.assertTrue(any("الدرجة" in reason for reason in reasons))
        self.assertTrue(any("الشحن" in reason for reason in reasons))

    def test_margin_and_score_thresholds_are_inclusive(self):
        self.assertEqual(eligibility_reasons(product(), 70, 15, 15), [])


if __name__ == "__main__":
    unittest.main()
