"""Server-side provider adapters for ProfitBot.

All live integrations are opt-in through environment variables. No provider is called
unless its credentials are configured. Supplier orders are created with payType=3
(create-only); this module never pays a supplier.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
import urllib.parse
from typing import Any


class ProviderNotConfigured(RuntimeError):
    pass


class ProviderRequestError(RuntimeError):
    pass


def _json_request(url: str, *, method: str = "POST", headers: dict[str, str] | None = None,
                  payload: Any = None, timeout: int = 20) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_000)
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", "replace")
        raise ProviderRequestError(f"Provider HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProviderRequestError(f"Provider connection failed: {type(exc).__name__}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderRequestError("Provider returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise ProviderRequestError("Provider returned an unexpected response")
    return data


def paypal_configured() -> bool:
    return bool(os.getenv("PAYPAL_CLIENT_ID") and os.getenv("PAYPAL_CLIENT_SECRET"))


def _paypal_base() -> str:
    mode = os.getenv("PAYPAL_ENV", "sandbox").strip().lower()
    if mode not in {"sandbox", "live"}:
        raise ProviderNotConfigured("PAYPAL_ENV must be sandbox or live")
    return "https://api-m.paypal.com" if mode == "live" else "https://api-m.sandbox.paypal.com"


def _paypal_token() -> str:
    client_id = os.getenv("PAYPAL_CLIENT_ID", "")
    secret = os.getenv("PAYPAL_CLIENT_SECRET", "")
    if not client_id or not secret:
        raise ProviderNotConfigured("PayPal credentials are not configured")
    credentials = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("ascii")
    request = urllib.request.Request(
        _paypal_base() + "/v1/oauth2/token",
        data=body,
        headers={"Authorization": "Basic " + credentials,
                 "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read(1_000_000).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, urllib.error.HTTPError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderRequestError("PayPal authentication failed") from exc
    token = result.get("access_token")
    if not token:
        raise ProviderRequestError("PayPal did not return an access token")
    return str(token)


def paypal_create_order(*, order_ref: str, amount: str, currency: str,
                        return_url: str, cancel_url: str) -> dict[str, Any]:
    token = _paypal_token()
    return _json_request(
        _paypal_base() + "/v2/checkout/orders",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                 "PayPal-Request-Id": "profitbot-" + order_ref + "-create"},
        payload={
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": order_ref,
                "custom_id": order_ref,
                "invoice_id": order_ref,
                "amount": {"currency_code": currency, "value": amount},
            }],
            "application_context": {
                "return_url": return_url,
                "cancel_url": cancel_url,
                "user_action": "PAY_NOW",
            },
        },
    )


def paypal_capture_order(paypal_order_id: str, *, order_ref: str) -> dict[str, Any]:
    token = _paypal_token()
    return _json_request(
        _paypal_base() + "/v2/checkout/orders/" + urllib.parse.quote(paypal_order_id, safe="") + "/capture",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                 "PayPal-Request-Id": "profitbot-" + order_ref + "-capture"},
        payload={},
    )


def paypal_verify_webhook(headers: dict[str, str], event: dict[str, Any]) -> bool:
    webhook_id = os.getenv("PAYPAL_WEBHOOK_ID", "")
    if not webhook_id:
        raise ProviderNotConfigured("PAYPAL_WEBHOOK_ID is not configured")
    token = _paypal_token()
    required = {
        "auth_algo": headers.get("paypal-auth-algo", ""),
        "cert_url": headers.get("paypal-cert-url", ""),
        "transmission_id": headers.get("paypal-transmission-id", ""),
        "transmission_sig": headers.get("paypal-transmission-sig", ""),
        "transmission_time": headers.get("paypal-transmission-time", ""),
        "webhook_id": webhook_id,
        "webhook_event": event,
    }
    if not all(required[k] for k in ("auth_algo", "cert_url", "transmission_id", "transmission_sig", "transmission_time")):
        return False
    result = _json_request(
        _paypal_base() + "/v1/notifications/verify-webhook-signature",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        payload=required,
    )
    return result.get("verification_status") == "SUCCESS"


def cj_configured() -> bool:
    return bool(os.getenv("CJ_API_KEY"))


def cj_access_token() -> str:
    api_key = os.getenv("CJ_API_KEY", "")
    if not api_key:
        raise ProviderNotConfigured("CJ_API_KEY is not configured")
    result = _json_request(
        "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken",
        headers={"Content-Type": "application/json"},
        payload={"apiKey": api_key},
    )
    if result.get("code") not in (0, 200):
        raise ProviderRequestError("CJ authentication failed: " + str(result.get("message", "unknown error"))[:180])
    token = (result.get("data") or {}).get("accessToken")
    if not token:
        raise ProviderRequestError("CJ did not return an access token")
    return str(token)


def cj_create_order_only(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a CJ order without confirming it or paying it.

    Sandbox is the default. Production order creation requires an explicit server-side
    CJ_LIVE_ORDER_CREATION=true flag. payType=3 is forced in both modes.
    """
    token = cj_access_token()
    live_enabled = os.getenv("CJ_LIVE_ORDER_CREATION", "false").strip().lower() == "true"
    request_payload = dict(payload)
    request_payload["payType"] = 3
    if not live_enabled:
        request_payload["isSandbox"] = 1
    result = _json_request(
        "https://developers.cjdropshipping.com/api2.0/v1/shopping/order/createOrderV3",
        headers={"CJ-Access-Token": token, "Content-Type": "application/json"},
        payload=request_payload,
    )
    if result.get("code") not in (0, 200) or result.get("success") is False:
        raise ProviderRequestError("CJ order creation failed: " + str(result.get("message", "unknown error"))[:180])
    return result


def tracking_configured() -> bool:
    return bool(os.getenv("TRACK17_API_KEY"))


def tracking_register(number: str, carrier: int | None = None) -> dict[str, Any]:
    api_key = os.getenv("TRACK17_API_KEY", "")
    if not api_key:
        raise ProviderNotConfigured("TRACK17_API_KEY is not configured")
    item: dict[str, Any] = {"number": number}
    if carrier is not None:
        item["carrier"] = carrier
    result = _json_request(
        "https://api.17track.net/track/v2.4/register",
        headers={"17token": api_key, "Content-Type": "application/json"},
        payload=[item],
    )
    if result.get("code") != 0:
        raise ProviderRequestError("17TRACK registration failed")
    return result
