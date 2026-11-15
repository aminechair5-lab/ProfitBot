from datetime import datetime, timezone, timedelta
import hashlib
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select, desc, func, text
from .config import settings
from .db import Base, engine, get_db
from .models import Product, Approval, AuditEvent, Supplier, SupplierOffer, CustomerOrder, TrendSignal, PaymentAttempt, SupplierFulfillment, ShipmentTracking, NotificationLog
from .schemas import ProductCreate, ApprovalCreate, ApprovalDecision, SupplierCreate, SupplierOfferCreate, StoreOrderCreate, OrderStatusUpdate, SupplierVerification, SupplierOfferVerification, PayPalCheckoutCreate, PayPalCapture, TrackingRegistration, FulfillmentPrepare, CJOrderCreate, SupplierPaymentConfirmation
from .security import require_owner
from .product_sources import discover_product_articles, MARKET_LOCALES, normalize
from .providers import (ProviderNotConfigured, ProviderRequestError, paypal_configured, paypal_create_order, paypal_capture_order, paypal_verify_webhook, cj_configured, cj_create_order_only, tracking_configured, tracking_register, tracking_verify_webhook, send_email_notification)

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


def supplier_offer_is_usable(db: Session, offer: SupplierOffer, market: str) -> bool:
    market = market.strip().upper()
    if not market or market == "DZ" or offer.verification_status != "verified":
        return False
    if offer.stock_status != "in_stock" or offer.shipping_cost is None:
        return False
    if offer.shipping_days_min is None or offer.shipping_days_max is None:
        return False
    if offer.currency != "USD" or offer.shipping_currency != "USD":
        return False
    product = db.get(Product, offer.product_id) if offer.product_id else None
    if not product or abs(product.supplier_cost - offer.unit_price) > 0.01:
        return False
    if abs(product.shipping_cost - float(offer.shipping_cost)) > 0.01:
        return False
    checked_at = offer.checked_at
    if checked_at is None:
        return False
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    if checked_at < datetime.now(timezone.utc) - timedelta(hours=24):
        return False
    destinations = {part.strip().upper() for part in offer.destination_markets.replace(";", ",").split(",")}
    supplier = db.get(Supplier, offer.supplier_id)
    return market in destinations and supplier is not None and supplier.verification_status == "verified"


def verified_supplier_offer(db: Session, product_id: int, market: str):
    """Return only a recently checked, in-stock offer from a verified supplier."""
    market = market.strip().upper()
    if not market or market == "DZ":
        return None
    rows = db.scalars(select(SupplierOffer).where(
        SupplierOffer.product_id == product_id
    ).order_by(desc(SupplierOffer.checked_at))).all()
    return next((offer for offer in rows if supplier_offer_is_usable(db, offer, market)), None)


def notify_customer(db: Session, order: CustomerOrder, event_type: str, subject: str, body: str):
    status = "disabled"
    detail = "SMTP is not configured"
    try:
        send_email_notification(recipient=order.customer_email, subject=subject, body=body)
        status, detail = "sent", "SMTP accepted the message"
    except ProviderNotConfigured as exc:
        detail = str(exc)
    except Exception as exc:
        status, detail = "failed", type(exc).__name__
    db.add(NotificationLog(order_ref=order.order_ref, event_type=event_type,
                           channel="email", recipient=order.customer_email,
                           status=status, detail=detail[:500]))

def profit_values(p: Product):
    fees = p.selling_price * (p.platform_fee_pct + p.payment_fee_pct + p.returns_reserve_pct) / 100
    net = p.selling_price - p.supplier_cost - p.shipping_cost - p.other_costs - fees
    margin = (net / p.selling_price * 100) if p.selling_price else 0
    return round(net, 2), round(margin, 2)

def eligibility_reasons(p: Product, score: float, net: float, margin: float):
    """Return actionable blockers for public listing; this is a screening gate, not verification."""
    reasons = []
    import re
    market = str(getattr(p, "target_market", "") or "").strip().upper()
    has_excluded_market = bool(
        re.search(r"(^|[\s,;/|])DZ($|[\s,;/|])", market)
        or "ALGERIA" in market
        or "الجزائر" in market
    )
    if has_excluded_market:
        reasons.append("السوق الجزائري غير مسموح في ProfitBot")
    if p.selling_price <= 0:
        reasons.append("أدخل سعر بيع موجباً")
    if not str(getattr(p, "supplier_name", "") or "").strip():
        reasons.append("أضف اسم المورد")
    if not str(getattr(p, "source_url", "") or "").strip():
        reasons.append("أضف رابط مصدر المنتج")
    if net <= 0:
        reasons.append("صافي الربح التقديري يجب أن يكون موجباً")
    if margin < 15:
        reasons.append("الهامش أقل من الحد الأدنى 15%")
    if score < 70:
        reasons.append("الدرجة أقل من الحد الأدنى 70")
    if getattr(p, "supplier_reliability", 0) < 60:
        reasons.append("موثوقية المورد أقل من 60/100")
    if getattr(p, "shipping_score", 0) < 50:
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

    # Multilingual, phrase-aware catalog. Normalize accents/case while preserving
    # non-Latin scripts so localized RSS titles can be classified too.
    import unicodedata
    product_catalog = {
        "Electronics": [
            "iphone", "smartphone", "mobile phone", "phone case", "phone charger", "wireless charger",
            "power bank", "headphones", "earbuds", "bluetooth speaker", "smartwatch", "laptop",
            "tablet", "keyboard", "computer mouse", "monitor", "digital camera", "projector",
            "gaming console", "game controller", "smartphone", "handy", "mobiltelefon", "kopfhörer",
            "écouteurs", "casque audio", "téléphone portable", "coque de téléphone", "chargeur sans fil",
            "auriculares", "teléfono móvil", "funda de móvil", "cargador inalámbrico", "portátil",
            "cuffie", "auricolari", "telefono cellulare", "custodia telefono", "draadloze koptelefoon",
            "koptelefoon", "hörlurar", "mobilskal", "スマートフォン", "ワイヤレスイヤホン", "モバイルバッテリー"
        ],
        "Home & Kitchen": [
            "air fryer", "coffee maker", "espresso machine", "vacuum cleaner", "robot vacuum",
            "water bottle", "storage organizer", "drawer organizer", "desk lamp", "led lamp",
            "office chair", "mattress", "pillow", "cookware", "kitchen gadget", "blender",
            "frying pan", "pressure cooker", "heißluftfritteuse", "kaffeemaschine", "staubsauger",
            "küchenmaschine", "friteuse sans huile", "machine à café", "aspirateur robot",
            "gourde", "organisateur de rangement", "lampe de bureau", "silla de oficina",
            "freidora de aire", "cafetera", "aspiradora", "botella reutilizable", "organizador",
            "friggitrice ad aria", "macchina da caffè", "aspirapolvere", "borraccia",
            "airfryer", "koffiezetapparaat", "stofzuiger", "vattenflaska", "luftrenare",
            "エアフライヤー", "コーヒーメーカー", "ロボット掃除機", "水筒", "収納ボックス"
        ],
        "Beauty & Personal Care": [
            "skin care", "skincare", "face serum", "moisturizer", "sunscreen", "makeup",
            "hair dryer", "hair straightener", "electric shaver", "perfume", "beauty device",
            "gesichtspflege", "sonnencreme", "haartrockner", "hautpflege", "sérum visage",
            "crème hydratante", "crème solaire", "soin de la peau", "sèche-cheveux",
            "suero facial", "crema hidratante", "protector solar", "cuidado de la piel",
            "secador de pelo", "siero viso", "crema solare", "cura della pelle",
            "gezichtsverzorging", "zonnebrandcrème", "huidverzorging", "hårfön",
            "美容液", "日焼け止め", "スキンケア", "ヘアドライヤー"
        ],
        "Fashion & Accessories": [
            "sneakers", "running shoes", "boots", "backpack", "handbag", "wallet", "sunglasses",
            "smart ring", "jacket", "dress", "jeans", "wristwatch", "necklace", "bracelet",
            "turnschuhe", "rucksack", "sonnenbrille", "handtasche", "mantel", "baskets",
            "chaussures de running", "sac à dos", "lunettes de soleil", "sac à main",
            "zapatillas", "mochila", "gafas de sol", "bolso", "chaqueta",
            "scarpe da ginnastica", "zaino", "occhiali da sole", "borsa",
            "rugzak", "zonnebril", "sneakers", "スニーカー", "リュック", "サングラス"
        ],
        "Sports & Fitness": [
            "yoga mat", "resistance bands", "dumbbells", "treadmill", "fitness tracker",
            "waterproof bag", "camping tent", "hiking shoes", "yogamatte", "hanteln",
            "tapis de yoga", "bandes de résistance", "haltères", "tapis de course",
            "esterilla de yoga", "bandas de resistencia", "mancuernas", "cinta de correr",
            "tappetino yoga", "fasce elastiche", "manubri", "yogamat", "motståndsband",
            "ヨガマット", "ダンベル", "ランニングマシン"
        ],
        "Pet Supplies": [
            "pet carrier", "cat litter", "dog harness", "pet toy", "pet bed",
            "hundegeschirr", "katzenstreu", "transportbox für hunde", "litière pour chat",
            "harnais pour chien", "jouet pour animaux", "arena para gatos", "arnés para perro",
            "juguete para mascotas", "lettiera per gatti", "guinzaglio per cani",
            "kattenbakvulling", "hondenharnas", "猫砂", "犬用ハーネス", "ペットベッド"
        ],
        "Toys & Gaming": [
            "lego set", "board game", "action figure", "toy", "gaming headset",
            "gesellschaftsspiel", "brettspiel", "spielzeug", "jeu de société", "figurine",
            "juego de mesa", "figura de acción", "juguete", "gioco da tavolo", "giocattolo",
            "bordspel", "speelgoed", "brädspel", "leksak", "ボードゲーム", "おもちゃ"
        ]
    }
    shopping_intent = [
        "buy", "best", "review", "price", "deal", "discount", "sale", "where to buy", "versus", "vs",
        "kaufen", "preis", "angebot", "test", "avis", "acheter", "prix", "promo", "meilleur",
        "comprar", "precio", "oferta", "mejor", "recensione", "prezzo", "offerta",
        "kopen", "prijs", "aanbieding", "köpa", "pris", "bäst", "購入", "価格", "おすすめ"
    ]
    non_commercial = [
        "breaking news", "election", "president", "prime minister", "football", "soccer",
        "basketball", "tennis", "cricket", "match result", "live score", "weather", "earthquake",
        "war", "death", "obituary", "celebrity", "actor", "actress", "singer", "concert",
        "movie", "film", "tv series", "episode", "championship", "tournament",
        "nachrichten", "wahl", "wetter", "erdbeben", "krieg", "élections", "météo",
        "tremblement de terre", "guerre", "noticias", "elecciones", "tiempo", "terremoto",
        "guerra", "elezioni", "meteo", "notizie", "nieuws", "verkiezingen", "väder",
        "ニュース", "選挙", "天気", "地震", "戦争"
    ]

    def normalize_title(value: str):
        value = unicodedata.normalize("NFKC", value).casefold()
        value = "".join(char for char in unicodedata.normalize("NFKD", value)
                        if not unicodedata.combining(char))
        return re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).strip()

    def has_phrase(normalized: str, term: str):
        phrase = normalize_title(term)
        return bool(phrase and re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", normalized, flags=re.UNICODE))

    def classify(title: str):
        normalized = normalize_title(title)
        matched = []
        categories = []
        for category, terms in product_catalog.items():
            category_hits = [term for term in terms if has_phrase(normalized, term)]
            if category_hits:
                categories.append(category)
                matched.extend(category_hits)
        blocked = [term for term in non_commercial if has_phrase(normalized, term)]
        if not matched or blocked:
            return None
        intent_hits = [term for term in shopping_intent if has_phrase(normalized, term)]
        score = min(95, 58 + min(18, (len(matched) - 1) * 9) + min(15, len(intent_hits) * 5))
        reasons = ["تطابق مع قاموس منتجات متعدد اللغات"]
        if len(matched) > 1:
            reasons.append("أكثر من مصطلح منتج")
        if intent_hits:
            reasons.append("وجود عبارة شراء أو مقارنة محلية")
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
    unclassified_items = []
    for item in root.findall(".//item")[:60]:
        scanned_count += 1
        fields = {child.tag.split("}")[-1]: (child.text or "").strip() for child in item}
        title = fields.get("title", "")
        classification = classify(title)
        if not classification:
            rejected_count += 1
            if title and len(unclassified_items) < 10:
                unclassified_items.append({"title": title, "url": fields.get("link", "")})
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
        "unclassified_count": rejected_count,
        "unclassified_items": unclassified_items,
        "filter": "Multilingual phrase-aware product catalog plus localized shopping-intent and non-commercial topic checks.",
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
            results.append({"geo": country, "count": result["count"], "scanned_count": result["scanned_count"],
                "unclassified_count": result.get("unclassified_count", 0),
                "unclassified_items": result.get("unclassified_items", [])})
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


@app.get("/signals/products/markets", dependencies=[Depends(require_owner)])
def discover_specialized_product_markets(markets: str = "US,GB,DE,CA"):
    """Discover product-specific editorial coverage from free, localized RSS feeds."""
    import re
    requested = list(dict.fromkeys(part.strip().upper() for part in markets.split(",") if part.strip()))
    if not requested or len(requested) > 4:
        raise HTTPException(400, "Choose between 1 and 4 markets")
    if any(not re.fullmatch(r"[A-Z]{2}", code) for code in requested):
        raise HTTPException(400, "Each market must be a two-letter country code")
    if "DZ" in requested:
        raise HTTPException(400, "The Algerian market is not supported by ProfitBot target-market discovery")
    unsupported = [code for code in requested if code not in MARKET_LOCALES]
    if unsupported:
        raise HTTPException(400, "Unsupported target markets: " + ", ".join(unsupported))

    scans = []
    failures = []
    grouped = {}
    for country in requested:
        try:
            result = discover_product_articles(country)
            scans.append({
                "geo": country,
                "scanned_count": result["scanned_count"],
                "count": result["matched_count"],
                "unclassified_count": result["unclassified_count"],
                "unclassified_items": result["unclassified_items"],
                "source": result["source"],
            })
            for item in result["items"]:
                key = normalize(item["title"])
                if not key:
                    continue
                current = grouped.setdefault(key, {
                    **item,
                    "markets": [],
                    "source_urls": [],
                    "market_count": 0,
                    "cross_market_signal": False,
                })
                if country not in current["markets"]:
                    current["markets"].append(country)
                if item["source_url"] and item["source_url"] not in current["source_urls"]:
                    current["source_urls"].append(item["source_url"])
                current["relevance_score"] = max(current["relevance_score"], item["relevance_score"])
        except RuntimeError as exc:
            failures.append({"geo": country, "error": str(exc)[:200]})

    items = list(grouped.values())
    for item in items:
        item["market_count"] = len(item["markets"])
        item["cross_market_signal"] = item["market_count"] >= 2
        # Review priority combines editorial relevance and breadth; it is not demand.
        breadth = (item["market_count"] / len(scans) * 100) if scans else 0
        item["discovery_priority_score"] = round(item["relevance_score"] * 0.7 + breadth * 0.3, 1)
        item["demand_verified"] = False
        item["sales_verified"] = False
        item["profitability_verified"] = False
        item["recommended_next_step"] = "تحقق يدوياً من المورد والسعر والمخزون والشحن والرسوم والضرائب والمنافسة."
    items.sort(key=lambda row: (row["discovery_priority_score"], row["market_count"]), reverse=True)

    return {
        "source": "Google News RSS (localized product/editorial search)",
        "source_type": "editorial_coverage",
        "market_scope": "international_only",
        "markets_requested": requested,
        "markets_scanned": scans,
        "failures": failures,
        "successful_market_count": len(scans),
        "rss_items_scanned_total": sum(row["scanned_count"] for row in scans),
        "matched_candidates_total": sum(row["count"] for row in scans),
        "unclassified_count_total": sum(row["unclassified_count"] for row in scans),
        "cross_market_count": sum(1 for item in items if item["cross_market_signal"]),
        "unclassified_samples": [
            {"geo": row["geo"], "title": sample["title"]}
            for row in scans for sample in row["unclassified_items"]
        ][:24],
        "items": items[:40],
        "warning": "المصدر مجاني ويعرض تغطية تحريرية لمنتجات في أخبار السوق، وليس حجم بحث المستهلكين أو مبيعات أو دليلاً على الطلب المدفوع. درجة الصلة وأولوية الفحص لا تثبت الربحية. تحقق يدوياً من المورد والسعر والمخزون والشحن والرسوم والضرائب والمنافسة قبل إضافة منتج أو نشره.",
    }


@app.get("/signals/opportunities", dependencies=[Depends(require_owner)])
def discover_product_opportunities(
    markets: str = "US,GB,DE,CA",
    min_markets: int = 1,
    limit: int = 30,
    db: Session = Depends(get_db),
):
    """Rank international product candidates by keyword relevance and cross-market breadth only."""
    if min_markets < 1 or min_markets > 4:
        raise HTTPException(400, "min_markets must be between 1 and 4")
    if limit < 1 or limit > 40:
        raise HTTPException(400, "limit must be between 1 and 40")

    comparison = compare_trend_markets(markets=markets, db=db)
    successful_markets = len(comparison["markets_scanned"])
    ranked = []
    for item in comparison["items"]:
        breadth = round((item["market_count"] / successful_markets) * 100, 1) if successful_markets else 0
        # This is an operational review priority, not a demand, sales, or profit estimate.
        priority = round(item["commercial_score"] * 0.7 + breadth * 0.3, 1)
        reasons = ["تطابق كلمات المنتج: " + str(item["commercial_score"]) + "/100"]
        reasons.append("اتساع الأسواق: " + str(item["market_count"]) + "/" + str(successful_markets))
        if item["cross_market_signal"]:
            reasons.append("ظهرت الإشارة في أكثر من سوق")
        ranked.append({
            **item,
            "market_breadth_score": breadth,
            "discovery_priority_score": priority,
            "priority_reasons": reasons,
            "signal_type": "search_interest",
            "commercially_verified": False,
            "demand_verified": False,
            "sales_verified": False,
            "profitability_verified": False,
            "recommended_next_step": "تحقق يدوياً من المورد والسعر والمخزون والشحن والرسوم والضرائب والمنافسة.",
        })

    ranked = [item for item in ranked if item["market_count"] >= min_markets]
    ranked.sort(
        key=lambda item: (item["discovery_priority_score"], item["market_count"], item["commercial_score"]),
        reverse=True,
    )
    for index, item in enumerate(ranked[:limit], start=1):
        item["rank"] = index

    markets_scanned = comparison["markets_scanned"]
    failures = comparison["failures"]
    return {
        "source": "Google Trends Trending RSS",
        "market_scope": "international_only",
        "markets_requested": comparison["markets_requested"],
        "markets_scanned": markets_scanned,
        "successful_market_count": len(markets_scanned),
        "failed_market_count": len(failures),
        "unclassified_count_total": sum(int(market.get("unclassified_count", 0) or 0) for market in markets_scanned),
        "unclassified_samples": [{"geo": market["geo"], **sample}
            for market in markets_scanned for sample in market.get("unclassified_items", [])][:20],
        "rss_items_scanned_total": sum(int(market.get("scanned_count", 0) or 0) for market in markets_scanned),
        "matched_candidates_total": sum(int(market.get("count", 0) or 0) for market in markets_scanned),
        "cross_market_count": comparison["cross_market_count"],
        "failures": failures,
        "min_markets": min_markets,
        "count": min(len(ranked), limit),
        "total_candidates_after_filter": len(ranked),
        "items": ranked[:limit],
        "score_interpretation": "Discovery priority is a heuristic review-priority score from keyword relevance (70%) and market breadth (30%). It is not search volume, purchase intent, demand, conversion, sales, or profit.",
        "warning": "هذه أولوية للفحص فقط، وليست قياساً للطلب أو المبيعات أو الربح. يلزم التحقق اليدوي من المورد والتكلفة والشحن والرسوم والضرائب والمنافسة قبل إضافة المنتج أو نشره.",
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



@app.post("/suppliers/{supplier_id}/verify", dependencies=[Depends(require_owner)])
def verify_supplier(supplier_id: int, data: SupplierVerification, db: Session = Depends(get_db)):
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    supplier.verification_status = "verified"
    supplier.reliability_score = data.reliability_score
    supplier.notes = (supplier.notes + "\\nVerification evidence: " + data.evidence_url + "\\n" + data.evidence_note).strip()
    audit(db, "supplier_verified", "supplier", supplier.id,
          f"reliability={data.reliability_score}; evidence={data.evidence_url}")
    db.commit()
    return {"id": supplier.id, "verification_status": supplier.verification_status,
            "reliability_score": supplier.reliability_score}


@app.post("/supplier-offers/{offer_id}/verify", dependencies=[Depends(require_owner)])
def verify_supplier_offer(offer_id: int, data: SupplierOfferVerification, db: Session = Depends(get_db)):
    offer = db.get(SupplierOffer, offer_id)
    if not offer:
        raise HTTPException(404, "Supplier offer not found")
    supplier = db.get(Supplier, offer.supplier_id)
    if not supplier or supplier.verification_status != "verified":
        raise HTTPException(409, "Verify the supplier with evidence before verifying an offer")
    if offer.stock_status != "in_stock" or offer.shipping_cost is None:
        raise HTTPException(409, "Offer must have confirmed in-stock status and a shipping cost")
    if offer.shipping_days_min is None or offer.shipping_days_max is None:
        raise HTTPException(409, "A confirmed delivery-time range is required")
    if not offer.product_id:
        raise HTTPException(409, "Link the offer to a ProfitBot product before verification")
    offer.verification_status = "verified"
    offer.checked_at = datetime.now(timezone.utc)
    audit(db, "supplier_offer_verified", "supplier_offer", offer.id,
          f"evidence={data.evidence_url}; note={data.evidence_note}")
    db.commit()
    return {"id": offer.id, "verification_status": offer.verification_status,
            "checked_at": offer.checked_at, "expires_in_hours": 24}


@app.post("/products/{product_id}/publish", dependencies=[Depends(require_owner)])
def publish_product(product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    score, eligible, net, margin = score_values(product)
    reasons = eligibility_reasons(product, score, net, margin)
    import re
    target_markets = [code for code in re.findall(r"(?<![A-Z0-9])[A-Z]{2}(?![A-Z0-9])", product.target_market.upper()) if code != "DZ"]
    if not target_markets or any(verified_supplier_offer(db, product.id, code) is None for code in target_markets):
        reasons.append("يلزم عرض مورد موثق وحديث ومتوفر ومناسب لكل سوق مستهدف قبل النشر")
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
    if verified_supplier_offer(db, product.id, data.destination_country) is None:
        raise HTTPException(409, "لا يمكن قبول الطلب قبل وجود عرض مورد موثق وحديث ومتوفر لهذا البلد مع تكلفة شحن ومدة تسليم مؤكدة")
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
        "tracking_number": o.tracking_number, "created_at": o.created_at,
        "fulfillment_status": (db.scalar(select(SupplierFulfillment.status).where(
            SupplierFulfillment.order_ref == o.order_ref
        ).order_by(desc(SupplierFulfillment.created_at)).limit(1)) or None),
        "cj_order_id": (db.scalar(select(SupplierFulfillment.provider_order_id).where(
            SupplierFulfillment.order_ref == o.order_ref
        ).order_by(desc(SupplierFulfillment.created_at)).limit(1)) or None)
    } for o in rows]


@app.post("/orders/{order_id}/status", dependencies=[Depends(require_owner)])
def update_customer_order(order_id: int, data: OrderStatusUpdate, db: Session = Depends(get_db)):
    order = db.get(CustomerOrder, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    allowed = {
        "pending_payment": {"payment_confirmed", "cancelled"},
        "payment_confirmed": {"cancelled"},
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
    notify_customer(db, order, "order_status_" + order.status,
                    "ProfitBot order update",
                    f"Your order {order.order_ref} status is now {order.status}.")
    db.commit()
    return {"order_ref": order.order_ref, "status": order.status}


@app.get("/integrations/status", dependencies=[Depends(require_owner)])
def integration_status():
    return {
        "paypal_checkout": {"configured": paypal_configured(), "environment": __import__("os").getenv("PAYPAL_ENV", "sandbox")},
        "cj_dropshipping": {"configured": cj_configured(), "live_order_creation_enabled": __import__("os").getenv("CJ_LIVE_ORDER_CREATION", "false").lower() == "true"},
        "tracking_17track": {"configured": tracking_configured()},
        "email_notifications": {"configured": all(__import__("os").getenv(k) for k in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"))},
        "note": "Missing credentials keep each provider disabled. Supplier payments are never made by ProfitBot."
    }


@app.get("/payments/paypal/availability")
def paypal_checkout_availability():
    import os
    return {"available": paypal_configured(), "environment": os.getenv("PAYPAL_ENV", "sandbox")}


@app.post("/payments/paypal/create-order")
def create_paypal_checkout(data: PayPalCheckoutCreate, db: Session = Depends(get_db)):
    if not paypal_configured():
        raise HTTPException(503, "PayPal is not configured. Add server-side PayPal credentials first.")
    from urllib.parse import urlsplit
    allowed_hosts = {"profitbot-484v.onrender.com"}
    allowed_hosts.update(urlsplit(origin).hostname for origin in settings.cors_origins if urlsplit(origin).hostname)
    if urlsplit(data.return_url).hostname not in allowed_hosts or urlsplit(data.cancel_url).hostname not in allowed_hosts:
        raise HTTPException(400, "PayPal return and cancel URLs must point to the configured ProfitBot storefront")
    order = db.scalar(select(CustomerOrder).where(CustomerOrder.order_ref == data.order_ref))
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status != "pending_payment":
        raise HTTPException(409, "Order is not awaiting customer payment")
    if verified_supplier_offer(db, order.product_id, order.destination_country) is None:
        raise HTTPException(409, "Supplier stock and shipping must be verified for this destination before checkout")
    existing = db.scalar(select(PaymentAttempt).where(
        PaymentAttempt.order_ref == order.order_ref,
        PaymentAttempt.status == "created"
    ).order_by(desc(PaymentAttempt.created_at)))
    if existing:
        raise HTTPException(409, "A PayPal checkout is already open for this order")
    try:
        result = paypal_create_order(order_ref=order.order_ref, amount=f"{order.total_amount:.2f}",
                                     currency=order.currency, return_url=data.return_url, cancel_url=data.cancel_url)
    except (ProviderNotConfigured, ProviderRequestError) as exc:
        raise HTTPException(502, str(exc)[:250])
    paypal_id = result.get("id")
    if result.get("status") != "CREATED" or not paypal_id:
        raise HTTPException(502, "PayPal did not create a valid checkout order")
    approve_url = next((link.get("href") for link in result.get("links", [])
                        if link.get("rel") in {"approve", "payer-action"}), None)
    if not approve_url:
        raise HTTPException(502, "PayPal did not return an approval URL")
    attempt = PaymentAttempt(order_ref=order.order_ref, provider="paypal",
                             provider_order_id=str(paypal_id), status="created",
                             amount=order.total_amount, currency=order.currency)
    db.add(attempt)
    audit(db, "paypal_checkout_created", "order", order.order_ref, f"paypal_order_id={paypal_id}")
    db.commit()
    return {"order_ref": order.order_ref, "paypal_order_id": paypal_id,
            "approval_url": approve_url, "environment": __import__("os").getenv("PAYPAL_ENV", "sandbox")}


@app.post("/payments/paypal/cancel")
def cancel_paypal_checkout(data: PayPalCapture, db: Session = Depends(get_db)):
    attempt = db.scalar(select(PaymentAttempt).where(
        PaymentAttempt.order_ref == data.order_ref,
        PaymentAttempt.provider_order_id == data.paypal_order_id,
        PaymentAttempt.provider == "paypal"
    ))
    if not attempt:
        raise HTTPException(404, "PayPal checkout attempt not found")
    if attempt.status == "created":
        attempt.status = "cancelled"
        attempt.updated_at = datetime.now(timezone.utc)
        audit(db, "paypal_checkout_cancelled", "order", data.order_ref, f"paypal_order_id={data.paypal_order_id}")
        db.commit()
    return {"order_ref": data.order_ref, "payment_attempt_status": attempt.status,
            "payment_collected": False}


@app.post("/payments/paypal/capture")
def capture_paypal_checkout(data: PayPalCapture, db: Session = Depends(get_db)):
    attempt = db.scalar(select(PaymentAttempt).where(
        PaymentAttempt.order_ref == data.order_ref,
        PaymentAttempt.provider_order_id == data.paypal_order_id,
        PaymentAttempt.provider == "paypal"
    ))
    if not attempt:
        raise HTTPException(404, "PayPal checkout attempt not found")
    order = db.scalar(select(CustomerOrder).where(CustomerOrder.order_ref == data.order_ref))
    if not order:
        raise HTTPException(404, "Order not found")
    if attempt.status == "captured" and order.status == "payment_confirmed":
        return {"order_ref": order.order_ref, "status": order.status, "idempotent": True}
    if order.status != "pending_payment":
        raise HTTPException(409, "Order is not awaiting payment")
    try:
        result = paypal_capture_order(data.paypal_order_id, order_ref=order.order_ref)
    except (ProviderNotConfigured, ProviderRequestError) as exc:
        raise HTTPException(502, str(exc)[:250])
    units = result.get("purchase_units") or []
    captures = ((units[0].get("payments") or {}).get("captures") or []) if units else []
    capture = captures[0] if captures else {}
    amount = capture.get("amount") or {}
    if capture.get("status") != "COMPLETED":
        raise HTTPException(409, "PayPal capture is not completed")
    if amount.get("currency_code") != order.currency or amount.get("value") != f"{order.total_amount:.2f}":
        raise HTTPException(409, "Captured amount or currency does not match the ProfitBot order")
    attempt.status = "captured"
    attempt.updated_at = datetime.now(timezone.utc)
    order.status = "payment_confirmed"
    order.payment_reference = "PayPal:" + str(capture.get("id") or data.paypal_order_id)
    order.updated_at = datetime.now(timezone.utc)
    audit(db, "paypal_payment_captured", "order", order.order_ref, f"capture_id={capture.get('id')}")
    notify_customer(db, order, "payment_confirmed", "ProfitBot payment confirmed",
                    f"Your ProfitBot order {order.order_ref} has been paid successfully. We will update you when fulfillment begins.")
    db.commit()
    return {"order_ref": order.order_ref, "status": order.status, "payment_reference": order.payment_reference}


@app.post("/webhooks/paypal")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        event = await request.json()
        valid = paypal_verify_webhook(dict(request.headers), event)
    except (ProviderNotConfigured, ProviderRequestError, ValueError):
        raise HTTPException(400, "PayPal webhook could not be verified")
    if not valid:
        raise HTTPException(401, "Invalid PayPal webhook signature")
    resource = event.get("resource") or {}
    related = ((resource.get("supplementary_data") or {}).get("related_ids") or {})
    paypal_order_id = related.get("order_id")
    if event.get("event_type") == "PAYMENT.CAPTURE.COMPLETED" and paypal_order_id:
        attempt = db.scalar(select(PaymentAttempt).where(PaymentAttempt.provider_order_id == paypal_order_id))
        if attempt and attempt.status != "captured":
            order = db.scalar(select(CustomerOrder).where(CustomerOrder.order_ref == attempt.order_ref))
            amount = resource.get("amount") or {}
            if order and order.status == "pending_payment" and resource.get("status") == "COMPLETED" and amount.get("currency_code") == order.currency and amount.get("value") == f"{order.total_amount:.2f}":
                attempt.status = "captured"
                attempt.updated_at = datetime.now(timezone.utc)
                order.status = "payment_confirmed"
                order.payment_reference = "PayPal:" + str(resource.get("id") or paypal_order_id)
                order.updated_at = datetime.now(timezone.utc)
                audit(db, "paypal_webhook_payment_captured", "order", order.order_ref, str(event.get("id", "")))
                notify_customer(db, order, "payment_confirmed", "ProfitBot payment confirmed",
                                f"Your ProfitBot order {order.order_ref} has been paid successfully.")
                db.commit()
    return {"received": True}


@app.post("/orders/{order_id}/fulfillment/request", dependencies=[Depends(require_owner)])
def request_supplier_fulfillment(order_id: int, data: FulfillmentPrepare, db: Session = Depends(get_db)):
    order = db.get(CustomerOrder, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status != "payment_confirmed":
        raise HTTPException(409, "Customer payment must be confirmed before requesting supplier fulfillment")
    offer = db.get(SupplierOffer, data.supplier_offer_id)
    if not offer or offer.product_id != order.product_id or not supplier_offer_is_usable(db, offer, order.destination_country):
        raise HTTPException(409, "Choose a fresh, verified supplier offer for this product and destination")
    supplier = db.get(Supplier, offer.supplier_id)
    if not supplier or supplier.verification_status != "verified":
        raise HTTPException(409, "Supplier is not verified")
    if offer.currency != "USD" or offer.shipping_currency != "USD":
        raise HTTPException(409, "Supplier offer must be recorded in USD until currency conversion is implemented")
    amount = round(offer.unit_price * order.quantity + (offer.shipping_cost or 0), 2)
    approval = Approval(action_type="purchase",
                        description=f"Supplier purchase approval for {order.order_ref}; offer #{offer.id}. {data.evidence_note}",
                        amount=amount, currency="USD", status="pending")
    db.add(approval)
    db.flush()
    fulfillment = SupplierFulfillment(order_ref=order.order_ref, supplier_id=supplier.id,
                                       supplier_offer_id=offer.id, provider="cj",
                                       status="approval_pending", approval_id=approval.id,
                                       notes=data.evidence_note)
    db.add(fulfillment)
    audit(db, "supplier_fulfillment_approval_requested", "order", order.order_ref,
          f"approval_id={approval.id}; offer_id={offer.id}; estimated_supplier_cost={amount:.2f} USD")
    db.commit()
    return {"order_ref": order.order_ref, "fulfillment_id": fulfillment.id,
            "approval_id": approval.id, "status": fulfillment.status,
            "estimated_supplier_cost": amount, "currency": "USD",
            "execution": "not_performed"}


@app.post("/orders/{order_id}/fulfillment/create-cj", dependencies=[Depends(require_owner)])
def create_cj_supplier_order(order_id: int, data: CJOrderCreate, db: Session = Depends(get_db)):
    import os
    order = db.get(CustomerOrder, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    fulfillment = db.scalar(select(SupplierFulfillment).where(
        SupplierFulfillment.order_ref == order.order_ref
    ).order_by(desc(SupplierFulfillment.created_at)))
    if not fulfillment or fulfillment.status not in {"approval_pending", "sandbox_created"}:
        raise HTTPException(409, "No pending supplier fulfillment approval exists")
    approval = db.get(Approval, fulfillment.approval_id) if fulfillment.approval_id else None
    if not approval or approval.status != "approved":
        raise HTTPException(409, "Explicit purchase approval is required before creating the supplier order")
    if order.status != "payment_confirmed":
        raise HTTPException(409, "Customer payment is not confirmed")
    offer = db.get(SupplierOffer, data.supplier_offer_id)
    if not offer or offer.id != fulfillment.supplier_offer_id or not offer.supplier_sku or not supplier_offer_is_usable(db, offer, order.destination_country):
        raise HTTPException(409, "The approved supplier offer must include a CJ SKU")
    if verified_supplier_offer(db, order.product_id, order.destination_country) is None:
        raise HTTPException(409, "Supplier stock/shipping verification has expired; re-check the offer")
    live_enabled = os.getenv("CJ_LIVE_ORDER_CREATION", "false").lower() == "true"
    if data.confirm_live_creation and not live_enabled:
        raise HTTPException(409, "Live CJ order creation is disabled on the server; sandbox mode remains active")
    payload = {
        "orderNumber": order.order_ref,
        "shippingZip": data.shipping_zip,
        "shippingCountryCode": order.destination_country,
        "shippingCountry": data.shipping_country_name,
        "shippingProvince": data.shipping_province,
        "shippingCity": data.shipping_city,
        "shippingPhone": data.shipping_phone,
        "shippingCustomerName": order.customer_name,
        "shippingAddress": order.shipping_address,
        "email": order.customer_email,
        "logisticName": data.logistic_name,
        "fromCountryCode": data.from_country_code.upper(),
        "shopLogisticsType": 2,
        "orderFlow": 1,
        "payType": 3,
        "products": [{"sku": offer.supplier_sku, "quantity": order.quantity,
                      "storeLineItemId": order.order_ref}],
    }
    try:
        result = cj_create_order_only(payload, allow_live=data.confirm_live_creation)
    except (ProviderNotConfigured, ProviderRequestError) as exc:
        raise HTTPException(502, str(exc)[:250])
    provider_data = result.get("data") or {}
    provider_order_id = provider_data.get("orderId")
    if not provider_order_id:
        raise HTTPException(502, "CJ did not return a supplier order ID")
    sandbox = not (live_enabled and data.confirm_live_creation)
    fulfillment.provider_order_id = str(provider_order_id)
    fulfillment.status = "sandbox_created" if sandbox else "created_unpaid"
    fulfillment.updated_at = datetime.now(timezone.utc)
    fulfillment.provider = "cj"
    fulfillment.notes = (fulfillment.notes + f"\\nCJ order created; paid=false; sandbox={sandbox}").strip()
    audit(db, "cj_supplier_order_created_unpaid", "order", order.order_ref,
          f"cj_order_id={provider_order_id}; paid=false; sandbox={sandbox}")
    db.commit()
    return {"order_ref": order.order_ref, "cj_order_id": provider_order_id,
            "fulfillment_status": fulfillment.status,
            "sandbox": sandbox,
            "supplier_payment": "not_performed",
            "next_step": "Pay the supplier manually in CJ after reviewing the order and cost; then record the supplier order reference in the order workflow."}



@app.post("/orders/{order_id}/fulfillment/confirm-supplier-payment", dependencies=[Depends(require_owner)])
def confirm_supplier_payment(order_id: int, data: SupplierPaymentConfirmation, db: Session = Depends(get_db)):
    order = db.get(CustomerOrder, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status != "payment_confirmed":
        raise HTTPException(409, "Customer payment must be confirmed first")
    fulfillment = db.scalar(select(SupplierFulfillment).where(
        SupplierFulfillment.order_ref == order.order_ref
    ).order_by(desc(SupplierFulfillment.created_at)))
    if not fulfillment or fulfillment.status != "created_unpaid":
        raise HTTPException(409, "A CJ supplier order in created_unpaid status is required")
    approval = db.get(Approval, fulfillment.approval_id) if fulfillment.approval_id else None
    if not approval or approval.status != "approved":
        raise HTTPException(409, "Approved purchase request is required")
    fulfillment.status = "supplier_paid"
    fulfillment.notes = (fulfillment.notes + "\\nManual supplier payment reference: " + data.payment_reference + "\\n" + data.evidence_note).strip()
    fulfillment.updated_at = datetime.now(timezone.utc)
    order.status = "supplier_ordered"
    order.updated_at = datetime.now(timezone.utc)
    audit(db, "supplier_payment_manually_confirmed", "order", order.order_ref,
          f"payment_reference={data.payment_reference}; supplier payment executed outside ProfitBot")
    notify_customer(db, order, "supplier_ordered", "Your order is being prepared",
                    f"Your order {order.order_ref} has been placed with the supplier. Tracking details will follow after dispatch.")
    db.commit()
    return {"order_ref": order.order_ref, "status": order.status,
            "fulfillment_status": fulfillment.status,
            "supplier_payment": "manually_recorded_not_executed_by_profitbot"}


@app.post("/tracking/register", dependencies=[Depends(require_owner)])
def register_shipment_tracking(data: TrackingRegistration, db: Session = Depends(get_db)):
    order = db.scalar(select(CustomerOrder).where(CustomerOrder.order_ref == data.order_ref))
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status not in {"supplier_ordered", "shipped"}:
        raise HTTPException(409, "Mark the supplier order as placed before registering shipment tracking")
    if not tracking_configured():
        raise HTTPException(503, "17TRACK API key is not configured")
    try:
        result = tracking_register(data.tracking_number, data.carrier_code)
    except (ProviderNotConfigured, ProviderRequestError) as exc:
        raise HTTPException(502, str(exc)[:250])
    accepted = ((result.get("data") or {}).get("accepted") or [])
    if not accepted:
        rejected = ((result.get("data") or {}).get("rejected") or [])
        raise HTTPException(409, "17TRACK rejected the tracking number: " + str(rejected[:1])[:180])
    tracking = ShipmentTracking(order_ref=order.order_ref, tracking_number=data.tracking_number,
                                carrier=str(data.carrier_code) if data.carrier_code else None,
                                provider="17track", status="registered")
    db.add(tracking)
    order.tracking_number = data.tracking_number
    order.status = "shipped"
    order.updated_at = datetime.now(timezone.utc)
    audit(db, "shipment_tracking_registered", "order", order.order_ref,
          f"provider=17track; tracking={data.tracking_number}")
    notify_customer(db, order, "shipped", "Your ProfitBot order has shipped",
                    f"Your order {order.order_ref} has shipped. Tracking number: {data.tracking_number}")
    db.commit()
    return {"order_ref": order.order_ref, "status": order.status, "tracking_number": data.tracking_number}


@app.post("/webhooks/17track")
async def tracking_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    if not tracking_verify_webhook(raw_body, request.headers.get("sign")):
        raise HTTPException(401, "Invalid 17TRACK webhook signature")
    try:
        event = __import__("json").loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(400, "Invalid tracking webhook payload")
    data = event.get("data") or {}
    number = data.get("number")
    tracking = db.scalar(select(ShipmentTracking).where(ShipmentTracking.tracking_number == number))
    if not tracking:
        return {"received": True, "matched": False}
    order = db.scalar(select(CustomerOrder).where(CustomerOrder.order_ref == tracking.order_ref))
    track_info = data.get("track_info") or {}
    latest_status = (track_info.get("latest_status") or {}).get("status") or event.get("event", "updated")
    latest_event = track_info.get("latest_event") or {}
    description = latest_event.get("description") or latest_event.get("description_translation", {}).get("description") or ""
    changed = tracking.status != latest_status or tracking.last_checkpoint != description
    tracking.status = str(latest_status)[:40]
    tracking.last_checkpoint = str(description)[:2000]
    tracking.checked_at = datetime.now(timezone.utc)
    if order and str(latest_status).casefold() == "delivered" and order.status == "shipped":
        order.status = "delivered"
        order.updated_at = datetime.now(timezone.utc)
    if order and changed:
        audit(db, "shipment_tracking_updated", "order", order.order_ref,
              f"status={latest_status}; checkpoint={description[:300]}")
        notify_customer(db, order, "tracking_updated", "ProfitBot shipment update",
                        f"Order {order.order_ref}: {latest_status}. {description}")
    db.commit()
    return {"received": True, "matched": True, "status": tracking.status}


@app.get("/track/{order_ref}")
def public_order_tracking(order_ref: str, email: str, db: Session = Depends(get_db)):
    order = db.scalar(select(CustomerOrder).where(CustomerOrder.order_ref == order_ref))
    if not order or order.customer_email.casefold() != email.strip().casefold():
        raise HTTPException(404, "Tracking details not found")
    tracking = db.scalar(select(ShipmentTracking).where(ShipmentTracking.order_ref == order_ref)
                         .order_by(desc(ShipmentTracking.checked_at)))
    return {"order_ref": order.order_ref, "product_name": order.product_name,
            "status": order.status, "tracking_number": tracking.tracking_number if tracking else order.tracking_number,
            "carrier": tracking.carrier if tracking else None,
            "tracking_status": tracking.status if tracking else None,
            "last_checkpoint": tracking.last_checkpoint if tracking else None}


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
