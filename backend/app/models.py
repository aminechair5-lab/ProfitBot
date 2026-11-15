from datetime import datetime, timezone
from sqlalchemy import String, Float, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def now_utc():
    return datetime.now(timezone.utc)

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    category: Mapped[str] = mapped_column(String(100), default="Uncategorized")
    target_market: Mapped[str] = mapped_column(String(100), default="Global - validate per country")
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    supplier_cost: Mapped[float] = mapped_column(Float, default=0)
    shipping_cost: Mapped[float] = mapped_column(Float, default=0)
    selling_price: Mapped[float] = mapped_column(Float, default=0)
    platform_fee_pct: Mapped[float] = mapped_column(Float, default=0)
    payment_fee_pct: Mapped[float] = mapped_column(Float, default=0)
    returns_reserve_pct: Mapped[float] = mapped_column(Float, default=0)
    other_costs: Mapped[float] = mapped_column(Float, default=0)
    demand_score: Mapped[int] = mapped_column(Integer, default=0)
    competition_score: Mapped[int] = mapped_column(Integer, default=0)
    supplier_reliability: Mapped[int] = mapped_column(Integer, default=0)
    shipping_score: Mapped[int] = mapped_column(Integer, default=0)
    marketing_fit: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(40), default="candidate")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    action_type: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(String(24), default="pending")
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    website_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    contact_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified")
    reliability_score: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class SupplierOffer(Base):
    __tablename__ = "supplier_offers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    product_title: Mapped[str] = mapped_column(String(220), index=True)
    source_url: Mapped[str] = mapped_column(String(1000))
    supplier_sku: Mapped[str | None] = mapped_column(String(120), nullable=True)
    unit_price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    shipping_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    shipping_currency: Mapped[str] = mapped_column(String(3), default="USD")
    destination_markets: Mapped[str] = mapped_column(String(500), default="")
    shipping_days_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shipping_days_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock_status: Mapped[str] = mapped_column(String(30), default="unknown")
    data_source: Mapped[str] = mapped_column(String(80), default="manual")
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class CustomerOrder(Base):
    __tablename__ = "customer_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_ref: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    product_name: Mapped[str] = mapped_column(String(180))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float)
    total_amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    customer_name: Mapped[str] = mapped_column(String(180))
    customer_email: Mapped[str] = mapped_column(String(254), index=True)
    destination_country: Mapped[str] = mapped_column(String(2))
    shipping_address: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending_payment", index=True)
    payment_reference: Mapped[str | None] = mapped_column(String(180), nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(180), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
