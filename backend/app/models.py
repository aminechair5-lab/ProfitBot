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
