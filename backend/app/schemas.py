from urllib.parse import urlsplit
from pydantic import BaseModel, Field, field_validator
from typing import Literal


class ProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    category: str = Field(default="Uncategorized", min_length=1, max_length=100)
    target_market: str = Field(default="Global - validate per country", min_length=1, max_length=100)
    source_url: str | None = Field(default=None, max_length=1000)
    supplier_name: str | None = Field(default=None, max_length=180)
    supplier_cost: float = Field(default=0, ge=0, allow_inf_nan=False)
    shipping_cost: float = Field(default=0, ge=0, allow_inf_nan=False)
    selling_price: float = Field(default=0, ge=0, allow_inf_nan=False)
    platform_fee_pct: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    payment_fee_pct: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    returns_reserve_pct: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    other_costs: float = Field(default=0, ge=0, allow_inf_nan=False)
    demand_score: int = Field(default=0, ge=0, le=100)
    competition_score: int = Field(default=0, ge=0, le=100)
    supplier_reliability: int = Field(default=0, ge=0, le=100)
    shipping_score: int = Field(default=0, ge=0, le=100)
    marketing_fit: int = Field(default=0, ge=0, le=100)

    @field_validator("name")
    @classmethod
    def name_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("name must contain at least two non-space characters")
        return value

    @field_validator("target_market")
    @classmethod
    def target_market_must_exclude_algeria(cls, value: str) -> str:
        value = value.strip()
        normalized = value.casefold()
        if normalized in {"dz", "algeria", "algeria (dz)", "الجزائر"}:
            raise ValueError("The Algerian market is excluded from ProfitBot target markets")
        if "الجزائر" in normalized or "algeria" in normalized:
            raise ValueError("The Algerian market is excluded from ProfitBot target markets")
        import re
        if re.search(r"(?<![A-Z0-9])DZ(?![A-Z0-9])", value, re.IGNORECASE):
            raise ValueError("The Algerian market is excluded from ProfitBot target markets")
        return value

    @field_validator("source_url")
    @classmethod
    def source_url_must_be_http_url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("source_url must be an absolute HTTP or HTTPS URL")
        if parsed.username or parsed.password:
            raise ValueError("source_url must not contain embedded credentials")
        return value.strip()


class ApprovalCreate(BaseModel):
    action_type: Literal["publish", "purchase", "payment", "refund", "price_change", "other"]
    description: str = Field(min_length=3, max_length=3000)
    amount: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str = Field(default="USD", min_length=3, max_length=8, pattern=r"^[A-Z]{3,8}$")


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=1000)


class SupplierCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    website_url: str | None = Field(default=None, max_length=1000)
    country_code: str | None = Field(default=None, min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")
    contact_url: str | None = Field(default=None, max_length=1000)
    notes: str = Field(default="", max_length=3000)

    @field_validator("name")
    @classmethod
    def supplier_name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Supplier name must contain at least two non-space characters")
        return value

    @field_validator("country_code")
    @classmethod
    def supplier_country_is_international(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.upper().strip()
        if value == "DZ":
            raise ValueError("The Algerian market is excluded from ProfitBot target markets")
        return value

    @field_validator("website_url", "contact_url")
    @classmethod
    def supplier_urls_are_http(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Supplier URLs must be absolute HTTP or HTTPS URLs without embedded credentials")
        return value.strip()


class SupplierOfferCreate(BaseModel):
    supplier_id: int = Field(gt=0)
    product_id: int | None = Field(default=None, gt=0)
    product_title: str = Field(min_length=2, max_length=220)
    source_url: str = Field(min_length=10, max_length=1000)
    supplier_sku: str | None = Field(default=None, max_length=120)
    unit_price: float = Field(ge=0, allow_inf_nan=False)
    currency: str = Field(default="USD", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    shipping_cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    shipping_currency: str = Field(default="USD", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    destination_markets: str = Field(min_length=2, max_length=500)
    shipping_days_min: int | None = Field(default=None, ge=0, le=365)
    shipping_days_max: int | None = Field(default=None, ge=0, le=365)
    stock_status: Literal["in_stock", "out_of_stock", "limited", "unknown"] = "unknown"
    data_source: Literal["manual", "official_api", "authorized_feed"] = "manual"

    @field_validator("product_title")
    @classmethod
    def offer_title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Product title must contain at least two non-space characters")
        return value

    @field_validator("source_url")
    @classmethod
    def offer_source_is_http(cls, value: str) -> str:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("source_url must be an absolute HTTP or HTTPS URL without embedded credentials")
        return value.strip()

    @field_validator("destination_markets")
    @classmethod
    def offer_destinations_are_international(cls, value: str) -> str:
        import re
        value = value.strip().upper()
        if re.search(r"(?<![A-Z0-9])DZ(?![A-Z0-9])", value):
            raise ValueError("The Algerian market is excluded from ProfitBot target markets")
        if "ALGERIA" in value or "الجزائر" in value:
            raise ValueError("The Algerian market is excluded from ProfitBot target markets")
        return value

    @field_validator("shipping_days_max")
    @classmethod
    def max_shipping_not_below_min(cls, value: int | None, info):
        minimum = info.data.get("shipping_days_min")
        if value is not None and minimum is not None and value < minimum:
            raise ValueError("shipping_days_max cannot be lower than shipping_days_min")
        return value


class StoreOrderCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=10)
    customer_name: str = Field(min_length=2, max_length=180)
    customer_email: str = Field(min_length=6, max_length=254)
    destination_country: str = Field(min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")
    shipping_address: str = Field(min_length=8, max_length=1000)
    # Hidden honeypot: real customers leave this field empty; basic bots often fill it.
    website: str = Field(default="", max_length=200)

    @field_validator("website")
    @classmethod
    def honeypot_must_be_empty(cls, value: str) -> str:
        if value.strip():
            raise ValueError("Invalid order request")
        return ""

    @field_validator("customer_name")
    @classmethod
    def customer_name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Customer name is required")
        return value

    @field_validator("customer_email")
    @classmethod
    def customer_email_basic_check(cls, value: str) -> str:
        import re
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]{2,}", value):
            raise ValueError("A valid customer email is required")
        return value

    @field_validator("destination_country")
    @classmethod
    def destination_must_be_supported(cls, value: str) -> str:
        value = value.upper()
        if value == "DZ":
            raise ValueError("This store does not accept orders for this destination")
        return value


class OrderStatusUpdate(BaseModel):
    status: Literal["payment_confirmed", "supplier_ordered", "shipped", "delivered", "cancelled"]
    payment_reference: str | None = Field(default=None, max_length=180)
    tracking_number: str | None = Field(default=None, max_length=180)
