import unittest

from pydantic import ValidationError

from app.schemas import StoreOrderCreate, OrderStatusUpdate


class StoreOrderValidationTests(unittest.TestCase):
    def valid_payload(self, **overrides):
        data = {
            "product_id": 1, "quantity": 2, "customer_name": "Jane Buyer",
            "customer_email": "jane@example.com", "destination_country": "US",
            "shipping_address": "123 Main Street, New York"
        }
        data.update(overrides)
        return data

    def test_accepts_valid_preliminary_order(self):
        order = StoreOrderCreate(**self.valid_payload())
        self.assertEqual(order.destination_country, "US")
        self.assertEqual(order.quantity, 2)

    def test_rejects_excluded_destination(self):
        with self.assertRaises(ValidationError):
            StoreOrderCreate(**self.valid_payload(destination_country="DZ"))

    def test_rejects_invalid_email(self):
        with self.assertRaises(ValidationError):
            StoreOrderCreate(**self.valid_payload(customer_email="not-an-email"))

    def test_quantity_is_limited(self):
        with self.assertRaises(ValidationError):
            StoreOrderCreate(**self.valid_payload(quantity=11))

    def test_order_status_cannot_be_arbitrary(self):
        with self.assertRaises(ValidationError):
            OrderStatusUpdate(status="paid_automatically")

    def test_shipping_requires_a_supported_status(self):
        update = OrderStatusUpdate(status="shipped", tracking_number="TRACK123")
        self.assertEqual(update.tracking_number, "TRACK123")


if __name__ == "__main__":
    unittest.main()
