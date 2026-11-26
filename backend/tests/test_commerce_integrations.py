import hashlib
import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.schemas import (
    SupplierVerification, SupplierOfferVerification, PayPalCheckoutCreate,
    CJOrderCreate, TrackingRegistration,
)
from app import providers


class CommerceSchemaTests(unittest.TestCase):
    def test_supplier_verification_requires_evidence(self):
        with self.assertRaises(ValidationError):
            SupplierVerification(evidence_url="https://example.com", evidence_note="short", reliability_score=70)

    def test_supplier_evidence_requires_https_or_http_url(self):
        with self.assertRaises(ValidationError):
            SupplierOfferVerification(evidence_url="javascript:alert(1)", evidence_note="Verified stock and price from supplier page")

    def test_paypal_return_urls_must_be_https(self):
        with self.assertRaises(ValidationError):
            PayPalCheckoutCreate(order_ref="PB-123456", return_url="http://example.com/return", cancel_url="https://example.com/cancel")

    def test_cj_order_defaults_are_safe(self):
        data = CJOrderCreate(
            shipping_country_name="United States", shipping_province="NY",
            shipping_city="New York", logistic_name="CJPacket",
            supplier_offer_id=1
        )
        self.assertFalse(data.confirm_live_creation)
        self.assertEqual(data.from_country_code, "CN")

    def test_cj_origin_excludes_algeria(self):
        with self.assertRaises(ValidationError):
            CJOrderCreate(
                shipping_country_name="United States", shipping_province="NY",
                shipping_city="New York", logistic_name="CJPacket",
                supplier_offer_id=1, from_country_code="DZ"
            )

    def test_tracking_number_requires_minimum_length(self):
        with self.assertRaises(ValidationError):
            TrackingRegistration(order_ref="PB-123456", tracking_number="123")


class ProviderSafetyTests(unittest.TestCase):
    def test_providers_are_disabled_without_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(providers.paypal_configured())
            self.assertFalse(providers.cj_configured())
            self.assertFalse(providers.tracking_configured())

    def test_tracking_webhook_signature_is_verified(self):
        body = b'{"event":"TRACKING_UPDATED","data":{"number":"RR123456789CN"}}'
        key = "test-secret"
        signature = hashlib.sha256(body + b"/" + key.encode()).hexdigest()
        with patch.dict(os.environ, {"TRACK17_API_KEY": key}, clear=True):
            self.assertTrue(providers.tracking_verify_webhook(body, signature))
            self.assertFalse(providers.tracking_verify_webhook(body, "0" * 64))

    def test_cj_order_creation_forces_no_payment_and_sandbox_by_default(self):
        with patch.dict(os.environ, {"CJ_API_KEY": "test-key"}, clear=True), \
             patch.object(providers, "cj_access_token", return_value="access-token"), \
             patch.object(providers, "_json_request", return_value={"code": 200, "success": True, "data": {"orderId": "CJ-1"}}) as request:
            result = providers.cj_create_order_only({"orderNumber": "PB-123456", "payType": 2})
        payload = request.call_args.kwargs["payload"]
        self.assertEqual(payload["payType"], 3)
        self.assertEqual(payload["isSandbox"], 1)
        self.assertEqual(result["data"]["orderId"], "CJ-1")

    def test_cj_available_logistics_uses_current_exact_route(self):
        with patch.dict(os.environ, {"CJ_API_KEY": "test-key"}, clear=True), \
             patch.object(providers, "cj_access_token", return_value="access-token"), \
             patch.object(providers, "_json_request", return_value={"code": 200, "result": True, "data": [{"logisticsName": "CJPacket Ordinary"}]}) as request:
            methods = providers.cj_available_logistics("CJ-SKU-1", "cn", "us")
        self.assertEqual(methods, ["CJPacket Ordinary"])
        self.assertEqual(request.call_args.kwargs["payload"], {
            "sku": "CJ-SKU-1", "startCountryCode": "CN", "destCountryCode": "US"
        })

    def test_cj_live_creation_needs_both_server_flag_and_per_order_confirmation(self):
        with patch.dict(os.environ, {"CJ_API_KEY": "test-key", "CJ_LIVE_ORDER_CREATION": "true"}, clear=True), \
             patch.object(providers, "cj_access_token", return_value="access-token"), \
             patch.object(providers, "_json_request", return_value={"code": 200, "success": True, "data": {"orderId": "CJ-2"}}) as request:
            providers.cj_create_order_only({"orderNumber": "PB-123456"}, allow_live=False)
        self.assertEqual(request.call_args.kwargs["payload"].get("isSandbox"), 1)
        with patch.dict(os.environ, {"CJ_API_KEY": "test-key", "CJ_LIVE_ORDER_CREATION": "true"}, clear=True), \
             patch.object(providers, "cj_access_token", return_value="access-token"), \
             patch.object(providers, "_json_request", return_value={"code": 200, "success": True, "data": {"orderId": "CJ-3"}}) as request:
            providers.cj_create_order_only({"orderNumber": "PB-123456"}, allow_live=True)
        self.assertNotIn("isSandbox", request.call_args.kwargs["payload"])


if __name__ == "__main__":
    unittest.main()
