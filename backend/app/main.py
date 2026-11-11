from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select, desc, func
from .config import settings
from .db import Base, engine, get_db
from .models import Product, Approval, AuditEvent
from .schemas import ProductCreate, ApprovalCreate, ApprovalDecision
from .security import require_owner

Base.metadata.create_all(bind=engine)
app = FastAPI(title="ProfitBot Cloud API", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

def audit(db: Session, event_type: str, entity_type: str, entity_id: str, detail: str = ""):
    db.add(AuditEvent(event_type=event_type, entity_type=entity_type, entity_id=str(entity_id), detail=detail))

def profit_values(p: Product):
    fees = p.selling_price * (p.platform_fee_pct + p.payment_fee_pct + p.returns_reserve_pct) / 100
    net = p.selling_price - p.supplier_cost - p.shipping_cost - p.other_costs - fees
    margin = (net / p.selling_price * 100) if p.selling_price else 0
    return round(net, 2), round(margin, 2)

def score_values(p: Product):
    net, margin = profit_values(p)
    margin_component = max(0, min(100, margin))
    score = (
        p.demand_score * .25
        + margin_component * .25
        + (100 - p.competition_score) * .15
        + p.supplier_reliability * .15
        + p.shipping_score * .10
        + p.marketing_fit * .10
    )
    eligible = (
        score >= 70 and net > 0 and margin >= 15
        and p.supplier_reliability >= 60 and p.shipping_score >= 50
    )
    return round(score, 1), eligible, net, margin

@app.get("/health")
def health():
    return {"status": "ok", "version": "0.4.0", "mode": "cloud-ready-starter", "live_integrations": False}

@app.get("/owner/summary", dependencies=[Depends(require_owner)])
def owner_summary(db: Session = Depends(get_db)):
    products = db.scalars(select(Product)).all()
    pending = db.scalar(select(func.count()).select_from(Approval).where(Approval.status == "pending")) or 0
    eligible = sum(1 for p in products if score_values(p)[1])
    return {
        "product_candidates": len(products),
        "eligible_candidates": eligible,
        "pending_approvals": pending,
        "monthly_net_profit": None,
        "monthly_net_profit_note": "No verified sales data connected yet",
        "target_monthly_profit_usd": 100,
        "live_integrations": False
    }

@app.get("/products", dependencies=[Depends(require_owner)])
def list_products(db: Session = Depends(get_db)):
    result = []
    for p in db.scalars(select(Product).order_by(desc(Product.created_at))).all():
        score, eligible, net, margin = score_values(p)
        result.append({
            "id": p.id, "name": p.name, "category": p.category, "target_market": p.target_market,
            "supplier_name": p.supplier_name, "score": score, "eligible": eligible,
            "estimated_net_profit": net, "estimated_margin_pct": margin, "status": p.status
        })
    return result

@app.post("/products", dependencies=[Depends(require_owner)])
def create_product(data: ProductCreate, db: Session = Depends(get_db)):
    p = Product(**data.model_dump())
    db.add(p)
    db.flush()
    score, eligible, net, margin = score_values(p)
    p.score = score
    audit(db, "product_created", "product", p.id, f"eligible={eligible}; net={net}; margin={margin}")
    db.commit()
    db.refresh(p)
    return {"id": p.id, "score": score, "eligible": eligible, "estimated_net_profit": net, "estimated_margin_pct": margin}

@app.post("/products/{product_id}/score", dependencies=[Depends(require_owner)])
def rescore_product(product_id: int, db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    score, eligible, net, margin = score_values(p)
    p.score = score
    audit(db, "product_scored", "product", p.id, f"score={score}; eligible={eligible}")
    db.commit()
    return {"id": p.id, "score": score, "eligible": eligible, "estimated_net_profit": net, "estimated_margin_pct": margin}

@app.post("/approvals", dependencies=[Depends(require_owner)])
def create_approval(data: ApprovalCreate, db: Session = Depends(get_db)):
    a = Approval(**data.model_dump(), status="pending")
    db.add(a)
    db.flush()
    audit(db, "approval_requested", "approval", a.id, f"type={a.action_type}; amount={a.amount} {a.currency}")
    db.commit()
    return {"id": a.id, "status": a.status, "execution": "not_performed"}

@app.get("/approvals", dependencies=[Depends(require_owner)])
def list_approvals(db: Session = Depends(get_db)):
    rows = db.scalars(select(Approval).order_by(desc(Approval.created_at)).limit(100)).all()
    return [{
        "id": a.id, "action_type": a.action_type, "description": a.description,
        "amount": a.amount, "currency": a.currency, "status": a.status,
        "decision_note": a.decision_note, "created_at": a.created_at
    } for a in rows]

@app.post("/approvals/{approval_id}/decision", dependencies=[Depends(require_owner)])
def decide_approval(approval_id: int, data: ApprovalDecision, db: Session = Depends(get_db)):
    a = db.get(Approval, approval_id)
    if not a:
        raise HTTPException(404, "Approval not found")
    if a.status != "pending":
        raise HTTPException(409, "Approval has already been decided")
    a.status = "approved" if data.decision == "approve" else "rejected"
    a.decision_note = data.note
    a.decided_at = datetime.now(timezone.utc)
    audit(db, f"approval_{a.status}", "approval", a.id, data.note or "")
    db.commit()
    return {"id": a.id, "status": a.status, "execution": "not_performed"}

@app.get("/audit", dependencies=[Depends(require_owner)])
def list_audit(db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditEvent).order_by(desc(AuditEvent.created_at)).limit(200)).all()
    return [{
        "id": e.id, "event_type": e.event_type, "entity_type": e.entity_type,
        "entity_id": e.entity_id, "detail": e.detail, "created_at": e.created_at
    } for e in rows]
