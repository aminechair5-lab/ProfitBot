from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select, desc, func, text
from .config import settings
from .db import Base, engine, get_db
from .models import Product, Approval, AuditEvent
from .schemas import ProductCreate, ApprovalCreate, ApprovalDecision
from .security import require_owner

Base.metadata.create_all(bind=engine)
app = FastAPI(title="ProfitBot Cloud API", version="0.5.0")

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


@app.get("/signals/trends", dependencies=[Depends(require_owner)])
def google_trend_signals(geo: str = "DZ"):
    """Classify public trending searches as product-related candidates, never as verified sales."""
    import re
    import urllib.error
    import urllib.request
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    country = geo.upper().strip()
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise HTTPException(400, "geo must be a two-letter country code")

    url = f"https://trends.google.com/trending/rss?geo={country}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ProfitBot/0.8 (+https://github.com/aminechair5-lab/ProfitBot)", "Accept": "application/rss+xml, application/xml"}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = response.read(1_500_000)
        root = ET.fromstring(payload)
    except (urllib.error.URLError, TimeoutError, ET.ParseError) as exc:
        raise HTTPException(502, f"Google Trends feed unavailable: {str(exc)[:180]}")

    # Phrase-aware catalog: avoids the previous bug where multiword terms such as
    # "air fryer" could never match a token-by-token comparison.
    product_catalog = {
        "Electronics": ["iphone", "smartphone", "mobile phone", "phone case", "phone charger",
            "wireless charger", "power bank", "headphones", "earbuds", "bluetooth speaker",
            "smartwatch", "laptop", "tablet", "keyboard", "computer mouse", "monitor",
            "digital camera", "projector", "gaming console", "game controller"],
        "Home & Kitchen": ["air fryer", "coffee maker", "espresso machine", "vacuum cleaner",
            "robot vacuum", "water bottle", "storage organizer", "drawer organizer",
            "desk lamp", "led lamp", "office chair", "mattress", "pillow", "cookware",
            "kitchen gadget", "blender", "frying pan", "pressure cooker"],
        "Beauty & Personal Care": ["skin care", "skincare", "face serum", "moisturizer",
            "sunscreen", "makeup", "hair dryer", "hair straightener", "electric shaver",
            "perfume", "beauty device"],
        "Fashion & Accessories": ["sneakers", "running shoes", "boots", "backpack",
            "handbag", "wallet", "sunglasses", "smart ring", "jacket", "dress", "jeans",
            "wristwatch", "necklace", "bracelet"],
        "Sports & Fitness": ["yoga mat", "resistance bands", "dumbbells", "treadmill",
            "fitness tracker", "waterproof bag", "camping tent", "hiking shoes"],
        "Pet Supplies": ["pet carrier", "cat litter", "dog harness", "pet toy", "pet bed"],
        "Toys & Gaming": ["lego set", "board game", "action figure", "toy", "gaming headset"]
    }
    shopping_intent = ["buy", "best", "review", "price", "deal", "discount", "sale",
        "where to buy", "versus", "vs"]
    non_commercial = ["breaking news", "election", "president", "prime minister",
        "football", "soccer", "basketball", "tennis", "cricket", "match result",
        "live score", "weather", "earthquake", "war", "death", "obituary",
        "celebrity", "actor", "actress", "singer", "concert", "movie", "film",
        "tv series", "episode", "championship", "tournament"]

    def classify(title: str):
        normalized = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
        matched = []
        categories = []
        for category, terms in product_catalog.items():
            category_hits = [term for term in terms
                if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", normalized)]
            if category_hits:
                categories.append(category)
                matched.extend(category_hits)
        blocked = [term for term in non_commercial
            if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", normalized)]
        if not matched or blocked:
            return None
        intent_hits = [term for term in shopping_intent
            if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", normalized)]
        score = min(95, 58 + min(18, (len(matched) - 1) * 9) + min(15, len(intent_hits) * 5))
        reasons = ["تطابق مع كلمات منتج معروفة"]
        if len(matched) > 1:
            reasons.append("أكثر من مصطلح منتج")
        if intent_hits:
            reasons.append("وجود نية شراء أو مقارنة")
        confidence = "medium" if score >= 70 else "low"
        return {
            "category": categories[0],
            "matched_product_terms": matched[:6],
            "shopping_intent_terms": intent_hits,
            "commercial_score": score,
            "confidence": confidence,
            "classification_reasons": reasons
        }

    candidates = []
    scanned_count = 0
    rejected_count = 0
    for item in root.findall(".//item")[:60]:
        scanned_count += 1
        fields = {child.tag.split("}")[-1]: (child.text or "").strip() for child in item}
        title = fields.get("title", "")
        classification = classify(title)
        if not classification:
            rejected_count += 1
            continue
        published = fields.get("pubDate")
        try:
            published_at = parsedate_to_datetime(published).isoformat() if published else None
        except (TypeError, ValueError):
            published_at = None
        candidates.append({
            "title": title,
            "url": fields.get("link", ""),
            "published_at": published_at,
            "approx_traffic": fields.get("approx_traffic"),
            "source": "Google Trends Trending RSS",
            "signal_type": "search_interest",
            "commercially_verified": False,
            "commercial_candidate": True,
            **classification
        })
    candidates.sort(key=lambda row: (row["commercial_score"], row.get("approx_traffic") or ""), reverse=True)
    return {
        "source": "Google Trends Trending RSS",
        "geo": country,
        "scanned_count": scanned_count,
        "count": len(candidates[:20]),
        "excluded_count": rejected_count,
        "filter": "Phrase-aware product catalog plus shopping-intent and non-commercial topic checks.",
        "warning": "النتائج إشارات بحث أولية فقط وليست دليلاً على المبيعات أو الربح. يلزم التحقق من المورد والسعر والشحن والرسوم والمنافسة والضرائب.",
        "items": candidates[:20]
    }

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    page = Path(__file__).with_name("dashboard.html").read_text(encoding="utf-8")
    return HTMLResponse(content=page)

@app.get("/health")
def health():
    # Verify the database as well as the web process before reporting readiness.
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {type(exc).__name__}")
    database_backend = "postgresql" if engine.dialect.name == "postgresql" else engine.dialect.name
    persistent_storage = database_backend == "postgresql"
    return {
        "status": "ok",
        "version": "0.5.0",
        "mode": "cloud-ready",
        "database": database_backend,
        "storage_persistent": persistent_storage,
        "storage_note": "PostgreSQL configured" if persistent_storage else "SQLite is suitable for local testing; hosted ephemeral filesystems may lose data on restart or redeploy.",
        "live_integrations": False
    }

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
        "live_integrations": False,
        "database": "postgresql" if engine.dialect.name == "postgresql" else engine.dialect.name,
        "storage_persistent": engine.dialect.name == "postgresql"
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
