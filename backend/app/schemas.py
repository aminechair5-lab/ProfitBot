from pydantic import BaseModel, Field, HttpUrl
from typing import Literal

class ProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    category: str = "Uncategorized"
    target_market: str = "Global - validate per country"
    source_url: str | None = None
    supplier_name: str | None = None
    supplier_cost: float = Field(default=0, ge=0)
    shipping_cost: float = Field(default=0, ge=0)
    selling_price: float = Field(default=0, ge=0)
    platform_fee_pct: float = Field(default=0, ge=0, le=100)
    payment_fee_pct: float = Field(default=0, ge=0, le=100)
    returns_reserve_pct: float = Field(default=0, ge=0, le=100)
    other_costs: float = Field(default=0, ge=0)
    demand_score: int = Field(default=0, ge=0, le=100)
    competition_score: int = Field(default=0, ge=0, le=100)
    supplier_reliability: int = Field(default=0, ge=0, le=100)
    shipping_score: int = Field(default=0, ge=0, le=100)
    marketing_fit: int = Field(default=0, ge=0, le=100)

class ApprovalCreate(BaseModel):
    action_type: Literal["publish", "purchase", "payment", "refund", "price_change", "other"]
    description: str = Field(min_length=3, max_length=3000)
    amount: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=8)

class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=1000)
