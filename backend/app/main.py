from datetime import datetime, timezone, timedelta
import hashlib
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select, desc, func, text
from .config import settings
from .db import Base, engine, get_db
from .models import Product, Approval, AuditEvent, Supplier, SupplierOffer, CustomerOrder, TrendSignal
from .schemas import ProductCreate, ApprovalCreate, ApprovalDecision, SupplierCreate, SupplierOfferCreate, StoreOrderCreate, OrderStatusUpdate
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

def eligibility_reasons(p: Product, score: float, net: float, margin: float):
    """Return actionable blockers for public listing; this is a screening gate, not verification."""
    reasons = []
    market = (p.target_market or "").strip().upper()
    if market == "DZ" or "ALGERIA" in market or "الجزائر" in market:
        reasons.append("السوق الجزائري غير مسموح في ProfitBot")
    if p.selling_price <= 0:
        reasons.append("أدخل سعر بيع موجباً")
    if not (p.supplier_name or "").strip():
        reasons.append("أضف اسم المورد")
    if not (p.source_url or "").strip():
        reasons.append("أضف رابط مصدر المنتج")
    if net <= 0:
        reasons.append("صافي الربح التقديري يجب أن يكون موجباً")
    if margin < 15:
        reasons.append("الهامش أقل من الحد الأدنى 15%")
    if score < 70:
        reasons.append("الدرجة أقل من الحد الأدنى 70")
    if p.supplier_reliability < 60:
        reasons.append("موثوقية المورد أقل من 60/100")
    if p.shipping_score < 50:
        reasons.append("درجة الشحن أقل من 50/100")
    return reasons


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
    score = round(score, 1)
    reasons = eligibility_reasons(p, score, net, margin)
    return score, not reasons, net, margin


@app.get("/signals/trends", dependencies=[Depends(require_owner)])
def google_trend_signals(geo: str = "US", db: Session = Depends(get_db)):
    """Classify public trending searches as product-related candidates, never as verified sales."""
    import re
    import urllib.error
    import urllib.request
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    country = geo.upper().strip()
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise HTTPException(400, "geo must be a two-letter country code")
    if country == "DZ":
        raise HTTPException(400, "The Algerian market is not supported by ProfitBot target-market discovery")

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
    observed_at = datetime.now(timezone.utc)
    for candidate in candidates[:20]:
        signal_key = hashlib.sha256((country + "|" + candidate["title"].casefold() + "|" + candidate["url"]).encode("utf-8")).hexdigest()
        saved = db.scalar(select(TrendSignal).where(TrendSignal.signal_key == signal_key))
        if saved is None:
            saved = TrendSignal(signal_key=signal_key, title=candidate["title"], geo=country,
                category=candidate["category"], source=candidate["source"], source_url=candidate["url"],
                signal_type=candidate["signal_type"], commercial_score=candidate["commercial_score"],
                confidence=candidate["confidence"], matched_terms=", ".join(candidate["matched_product_terms"]),
                published_at=candidate["published_at"], observed_at=observed_at)
            db.add(saved)
        else:
            saved.commercial_score = candidate["commercial_score"]
            saved.confidence = candidate["confidence"]
            saved.observed_at = observed_at
    db.commit()
    return {
        "source": "Google Trends Trending RSS",
        "geo": country,
        "market_scope": "international_only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scanned_count": scanned_count,
        "count": len(candidates[:20]),
        "excluded_count": rejected_count,
        "filter": "Phrase-aware product catalog plus shopping-intent and non-commercial topic checks.",
        "score_interpretation": "Heuristic keyword relevance only; not search volume, demand, conversion, sales or profit.",
        "warning": "النتائج إشارات بحث أولية فقط وليست دليلاً على المبيعات أو الربح. درجة التطابق لا تقيس حجم الطلب. يلزم التحقق من المورد والسعر والشحن والرسوم والمنافسة والضرائب.",
        "items": candidates[:20]
    }

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    page = Path(__file__).with_name("dashboard.html").read_text(encoding="utf-8")
    return HTMLResponse(content=page)

@app.get("/store", response_class=HTMLResponse)
def public_storefront():
    page = Path(__file__).with_name("storefront.html").read_text(encoding="utf-8")
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




@app.get("/signals/trends/markets", dependencies=[Depends(require_owner)])
def compare_trend_markets(markets: str = "US,GB,DE,CA", db: Session = Depends(get_db)):
    """Compare public product-related search-interest candidates across a few international markets."""
    import re
    requested = list(dict.fromkeys(part.strip().upper() for part in markets.split(",") if part.strip()))
    if not requested or len(requested) > 4:
        raise HTTPException(400, "Choose between 1 and 4 markets")
    if any(not re.fullmatch(r"[A-Z]{2}", code) for code in requested):
        raise HTTPException(400, "Each market must be a two-letter country code")
    if "DZ" in requested:
        raise HTTPException(400, "The Algerian market is not supported by ProfitBot target-market discovery")

    results = []
    failures = []
    grouped = {}
    for country in requested:
        try:
            result = google_trend_signals(geo=country, db=db)
            results.append({"geo": country, "count": result["count"], "scanned_count": result["scanned_count"]})
            for item in result["items"]:
                key = re.sub(r"[^a-z0-9]+", " ", item["title"].casefold()).strip()
                if not key:
                    continue
                grouped.setdefault(key, {"title": item["title"], "category": item["category"],
                    "commercial_score": item["commercial_score"], "confidence": item["confidence"],
                    "source": item["source"], "source_url": item["url"], "markets": []})
                grouped[key]["commercial_score"] = max(grouped[key]["commercial_score"], item["commercial_score"])
                if country not in grouped[key]["markets"]:
                    grouped[key]["markets"].append(country)
        except HTTPException as exc:
            failures.append({"geo": country, "error": str(exc.detail)[:200]})

    items = list(grouped.values())
    for item in items:
        item["market_count"] = len(item["markets"])
        item["cross_market_signal"] = item["market_count"] >= 2
        item["score_interpretation"] = "Heuristic keyword relevance only; not demand or sales."
    items.sort(key=lambda item: (item["market_count"], item["commercial_score"]), reverse=True)
    return {
        "market_scope": "international_only",
        "markets_requested": requested,
        "markets_scanned": results,
        "failures": failures,
        "count": len(items),
        "cross_market_count": sum(1 for item in items if item["cross_market_signal"]),
        "warning": "تكرار الإشارة بين الأسواق يزيد أولوية الفحص فقط؛ لا يثبت المبيعات أو الطلب المدفوع.",
        "items": items[:40]
    }

@app.get("/signals/history", dependencies=[Depends(require_owner)])
def trend_signal_history(geo: str | None = None, db: Session = Depends(get_db)):
    query = select(TrendSignal).order_by(desc(TrendSignal.observed_at)).limit(300)
    if geo:
        country = geo.upper().strip()
        if len(country) != 2 or country == "DZ":
            raise HTTPException(400, "Use a supported two-letter international country code")
        query = query.where(TrendSignal.geo == country)
    rows = db.scalars(query).all()
    return [{
        "id": row.id, "title": row.title, "geo": row.geo, "category": row.category,
        "source": row.source, "source_url": row.source_url, "signal_type": row.signal_type,
        "commercial_score": row.commercial_score, "confidence": row.confidence,
        "matched_terms": row.matched_terms, "published_at": row.published_at,
        "observed_at": row.observed_at, "commercially_verified": False
    } for row in rows]

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
            "eligibility_reasons": eligibility_reasons(p, score, net, margin),
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
    return {"id": p.id, "score": score, "eligible": eligible,
            "eligibility_reasons": eligibility_reasons(p, score, net, margin),
            "estimated_net_profit": net, "estimated_margin_pct": margin}

@app.post("/products/{product_id}/score", dependencies=[Depends(require_owner)])
def rescore_product(product_id: int, db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    score, eligible, net, margin = score_values(p)
    p.score = score
    audit(db, "product_scored", "product", p.id, f"score={score}; eligible={eligible}")
    db.commit()
    return {"id": p.id, "score": score, "eligible": eligible,
            "eligibility_reasons": eligibility_reasons(p, score, net, margin),
            "estimated_net_profit": net, "estimated_margin_pct": margin}


@app.post("/suppliers", dependencies=[Depends(require_owner)])
def create_supplier(data: SupplierCreate, db: Session = Depends(get_db)):
    supplier = Supplier(**data.model_dump(), verification_status="unverified", reliability_score=0)
    db.add(supplier)
    db.flush()
    audit(db, "supplier_created", "supplier", supplier.id, "verification_status=unverified")
    db.commit()
    db.refresh(supplier)
    return {"id": supplier.id, "name": supplier.name, "verification_status": supplier.verification_status,
            "reliability_score": supplier.reliability_score}


@app.get("/suppliers", dependencies=[Depends(require_owner)])
def list_suppliers(db: Session = Depends(get_db)):
    rows = db.scalars(select(Supplier).order_by(desc(Supplier.created_at)).limit(200)).all()
    return [{
        "id": row.id, "name": row.name, "website_url": row.website_url,
        "country_code": row.country_code, "contact_url": row.contact_url,
        "verification_status": row.verification_status, "reliability_score": row.reliability_score,
        "notes": row.notes, "created_at": row.created_at
    } for row in rows]


@app.post("/supplier-offers", dependencies=[Depends(require_owner)])
def create_supplier_offer(data: SupplierOfferCreate, db: Session = Depends(get_db)):
    supplier = db.get(Supplier, data.supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    if data.product_id is not None and not db.get(Product, data.product_id):
        raise HTTPException(404, "Linked product not found")
    offer_data = data.model_dump()
    offer = SupplierOffer(**offer_data, verification_status="unverified")
    db.add(offer)
    db.flush()
    audit(db, "supplier_offer_created", "supplier_offer", offer.id,
          f"supplier_id={supplier.id}; data_source={offer.data_source}; verified=false")
    db.commit()
    db.refresh(offer)
    return {"id": offer.id, "supplier_id": offer.supplier_id, "product_id": offer.product_id,
            "verification_status": offer.verification_status, "checked_at": offer.checked_at}


@app.get("/supplier-offers", dependencies=[Depends(require_owner)])
def list_supplier_offers(supplier_id: int | None = None, product_id: int | None = None,
                         db: Session = Depends(get_db)):
    query = select(SupplierOffer).order_by(desc(SupplierOffer.checked_at)).limit(300)
    if supplier_id is not None:
        query = query.where(SupplierOffer.supplier_id == supplier_id)
    if product_id is not None:
        query = query.where(SupplierOffer.product_id == product_id)
    rows = db.scalars(query).all()
    return [{
        "id": row.id, "supplier_id": row.supplier_id, "product_id": row.product_id,
        "product_title": row.product_title, "source_url": row.source_url,
        "supplier_sku": row.supplier_sku, "unit_price": row.unit_price, "currency": row.currency,
        "shipping_cost": row.shipping_cost, "shipping_currency": row.shipping_currency,
        "destination_markets": row.destination_markets, "shipping_days_min": row.shipping_days_min,
        "shipping_days_max": row.shipping_days_max, "stock_status": row.stock_status,
        "data_source": row.data_source, "verification_status": row.verification_status,
        "checked_at": row.checked_at
    } for row in rows]


@app.post("/products/{product_id}/publish", dependencies=[Depends(require_owner)])
def publish_product(product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    score, eligible, net, margin = score_values(product)
    reasons = eligibility_reasons(product, score, net, margin)
    if reasons:
        raise HTTPException(409, "لا يمكن نشر المنتج: " + "؛ ".join(reasons))
    product.status = "published"
    product.score = score
    audit(db, "product_published", "product", product.id, "public storefront; supplier and fulfilment still require manual confirmation")
    db.commit()
    return {"id": product.id, "status": product.status, "score": score,
            "estimated_net_profit": net, "estimated_margin_pct": margin,
            "notice": "Listing is visible; supplier stock, shipping and payment are not automatically verified."}


@app.get("/store/products")
def public_store_products(db: Session = Depends(get_db)):
    rows = db.scalars(select(Product).where(Product.status == "published").order_by(desc(Product.created_at)).limit(100)).all()
    return [{
        "id": p.id, "name": p.name, "category": p.category, "target_market": p.target_market,
        "price": p.selling_price, "currency": "USD", "description": "منتج معروض من متجر ProfitBot. يتم تأكيد التوفر والشحن يدوياً قبل تحصيل أي مبلغ."
    } for p in rows]


@app.post("/store/orders")
def create_store_order(data: StoreOrderCreate, db: Session = Depends(get_db)):
    # Lightweight persistent abuse control: cap repeated submissions per normalized email.
    rate_window_start = datetime.now(timezone.utc) - timedelta(minutes=15)
    recent_email_orders = db.scalar(select(func.count()).select_from(CustomerOrder).where(
        CustomerOrder.customer_email == data.customer_email,
        CustomerOrder.created_at >= rate_window_start
    )) or 0
    if recent_email_orders >= 3:
        raise HTTPException(429, "Too many order requests from this email. Please try again later.")
    product = db.get(Product, data.product_id)
    if not product or product.status != "published":
        raise HTTPException(404, "Product is not available in the store")
    if product.selling_price <= 0:
        raise HTTPException(409, "Product price is not configured")
    import secrets
    order = CustomerOrder(
        order_ref="PB-" + secrets.token_hex(5).upper(),
        product_id=product.id, product_name=product.name, quantity=data.quantity,
        unit_price=product.selling_price, total_amount=round(product.selling_price * data.quantity, 2),
        currency="USD", customer_name=data.customer_name, customer_email=data.customer_email,
        destination_country=data.destination_country, shipping_address=data.shipping_address,
        status="pending_payment"
    )
    db.add(order)
    db.flush()
    audit(db, "store_order_created", "order", order.order_ref, "status=pending_payment; payment not collected")
    db.commit()
    return {"order_ref": order.order_ref, "status": order.status, "total_amount": order.total_amount,
            "currency": order.currency,
            "message": "تم استلام طلبك مبدئياً. لم يتم تحصيل أي مبلغ؛ سيتم تأكيد التوفر والشحن ووسيلة الدفع معك."}


@app.get("/orders", dependencies=[Depends(require_owner)])
def list_customer_orders(db: Session = Depends(get_db)):
    rows = db.scalars(select(CustomerOrder).order_by(desc(CustomerOrder.created_at)).limit(200)).all()
    return [{
        "id": o.id, "order_ref": o.order_ref, "product_name": o.product_name, "quantity": o.quantity,
        "total_amount": o.total_amount, "currency": o.currency, "customer_name": o.customer_name,
        "customer_email": o.customer_email, "destination_country": o.destination_country,
        "status": o.status, "payment_reference": o.payment_reference,
        "tracking_number": o.tracking_number, "created_at": o.created_at
    } for o in rows]


@app.post("/orders/{order_id}/status", dependencies=[Depends(require_owner)])
def update_customer_order(order_id: int, data: OrderStatusUpdate, db: Session = Depends(get_db)):
    order = db.get(CustomerOrder, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    allowed = {
        "pending_payment": {"payment_confirmed", "cancelled"},
        "payment_confirmed": {"supplier_ordered", "cancelled"},
        "supplier_ordered": {"shipped", "cancelled"},
        "shipped": {"delivered"},
        "delivered": set(), "cancelled": set()
    }
    if data.status not in allowed.get(order.status, set()):
        raise HTTPException(409, f"Invalid order transition: {order.status} -> {data.status}")
    if data.status == "payment_confirmed" and not data.payment_reference:
        raise HTTPException(400, "Record a verified external payment reference before confirming payment")
    if data.status == "shipped" and not data.tracking_number:
        raise HTTPException(400, "Tracking number is required before marking an order shipped")
    order.status = data.status
    if data.payment_reference:
        order.payment_reference = data.payment_reference
    if data.tracking_number:
        order.tracking_number = data.tracking_number
    order.updated_at = datetime.now(timezone.utc)
    audit(db, "order_status_updated", "order", order.order_ref, f"status={order.status}")
    db.commit()
    return {"order_ref": order.order_ref, "status": order.status}

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
