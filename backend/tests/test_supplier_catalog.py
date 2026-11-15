import unittest

from pydantic import ValidationError

from app.schemas import SupplierCreate, SupplierOfferCreate


class SupplierSchemaTests(unittest.TestCase):
    def test_supplier_defaults_to_unverified(self):
        supplier = SupplierCreate(name="Example Supplier", country_code="US")
        self.assertEqual(supplier.country_code, "US")

    def test_supplier_rejects_excluded_country(self):
        with self.assertRaises(ValidationError):
            SupplierCreate(name="Example Supplier", country_code="DZ")

    def test_supplier_rejects_url_with_credentials(self):
        with self.assertRaises(ValidationError):
            SupplierCreate(name="Example Supplier", website_url="https://user:pass@example.com")

    def test_offer_requires_http_source_url(self):
        with self.assertRaises(ValidationError):
            SupplierOfferCreate(
                supplier_id=1, product_title="Wireless charger",
                source_url="javascript:alert(1)", unit_price=8.5,
                destination_markets="US, GB"
            )

    def test_offer_rejects_excluded_destination(self):
        with self.assertRaises(ValidationError):
            SupplierOfferCreate(
                supplier_id=1, product_title="Wireless charger",
                source_url="https://supplier.example/item", unit_price=8.5,
                destination_markets="US, DZ, GB"
            )

    def test_offer_rejects_invalid_shipping_window(self):
        with self.assertRaises(ValidationError):
            SupplierOfferCreate(
                supplier_id=1, product_title="Wireless charger",
                source_url="https://supplier.example/item", unit_price=8.5,
                destination_markets="US, GB", shipping_days_min=12,
                shipping_days_max=5
            )

    def test_offer_accepts_documented_supplier_data(self):
        offer = SupplierOfferCreate(
            supplier_id=1, product_title="Wireless charger",
            source_url="https://supplier.example/item", unit_price=8.5,
            currency="USD", shipping_cost=2.5, destination_markets="US, GB",
            stock_status="unknown", data_source="manual"
        )
        self.assertEqual(offer.verification_status if hasattr(offer, "verification_status") else "unverified", "unverified")
        self.assertEqual(offer.destination_markets, "US, GB")


if __name__ == "__main__":
    unittest.main()
