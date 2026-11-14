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
