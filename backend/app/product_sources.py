"""Free, market-localized editorial product discovery via Google News RSS.

These are product-coverage signals, not consumer search volume, sales, or proof of demand.
"""
from __future__ import annotations

import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

MARKET_LOCALES = {
    "US": ("en-US", "en"),
    "GB": ("en-GB", "en"),
    "DE": ("de-DE", "de"),
    "CA": ("en-CA", "en"),
    "FR": ("fr-FR", "fr"),
    "AU": ("en-AU", "en"),
    "AE": ("en-AE", "en"),
    "SA": ("en-SA", "en"),
    "ES": ("es-ES", "es"),
    "IT": ("it-IT", "it"),
    "NL": ("nl-NL", "nl"),
    "SE": ("sv-SE", "sv"),
    "JP": ("ja-JP", "ja"),
    "SG": ("en-SG", "en"),
    "BR": ("pt-BR", "pt"),
    "MX": ("es-MX", "es"),
}

PRODUCT_TERMS = {
    "Electronics": [
        "wireless earbuds", "bluetooth speaker", "power bank", "smartwatch", "smart phone",
        "smartphone", "phone case", "wireless charger", "gaming console", "tablet", "laptop",
        "kabellose kopfhörer", "bluetooth lautsprecher", "powerbank", "smartwatch",
        "écouteurs sans fil", "enceinte bluetooth", "batterie externe", "montre connectée",
        "auriculares inalámbricos", "altavoz bluetooth", "batería externa", "reloj inteligente",
        "auricolari wireless", "cassa bluetooth", "batteria esterna", "koptelefoon",
        "draadloze oordopjes", "hörlurar", "trådlösa hörlurar", "ワイヤレスイヤホン",
        "スマートウォッチ", "モバイルバッテリー", "fone sem fio", "relógio inteligente",
    ],
    "Home & Kitchen": [
        "air fryer", "robot vacuum", "coffee maker", "espresso machine", "air purifier",
        "portable blender", "water bottle", "heated blanket", "kitchen gadget", "blender",
        "heißluftfritteuse", "saugroboter", "kaffeemaschine", "luftreiniger",
        "friteuse sans huile", "aspirateur robot", "machine à café", "purificateur d'air",
        "freidora de aire", "aspiradora robot", "cafetera", "purificador de aire",
        "friggitrice ad aria", "robot aspirapolvere", "macchina da caffè",
        "airfryer", "robotstofzuiger", "koffiezetapparaat", "luftrenare",
        "エアフライヤー", "ロボット掃除機", "コーヒーメーカー", "空気清浄機",
        "fritadeira sem óleo", "aspirador robô", "cafeteira",
    ],
    "Beauty & Personal Care": [
        "face serum", "skincare device", "hair dryer", "hair straightener", "sunscreen",
        "makeup brush", "electric shaver", "gesichtsserum", "haartrockner", "sonnencreme",
        "sérum visage", "sèche-cheveux", "crème solaire", "suero facial", "secador de pelo",
        "protector solar", "siero viso", "asciugacapelli", "crema solare",
        "gezichtsserum", "huidverzorging", "美容液", "ヘアドライヤー", "日焼け止め",
    ],
    "Fashion & Accessories": [
        "running shoes", "sneakers", "smart ring", "backpack", "handbag", "sunglasses",
        "turnschuhe", "rucksack", "handtasche", "sonnenbrille", "smart ring",
        "chaussures de running", "sac à dos", "sac à main", "lunettes de soleil",
        "zapatillas de running", "mochila", "bolso", "gafas de sol",
        "scarpe da running", "zaino", "borsa", "occhiali da sole",
        "rugzak", "zonnebril", "löparskor", "ryggsäck", "スニーカー", "リュック",
    ],
    "Sports & Fitness": [
        "yoga mat", "resistance bands", "fitness tracker", "camping tent", "dumbbells",
        "yogamatte", "widerstandsbänder", "hanteln", "tapis de yoga", "bandes de résistance",
        "haltères", "esterilla de yoga", "bandas de resistencia", "mancuernas",
        "tappetino yoga", "fasce elastiche", "manubri", "yogamat", "motståndsband",
        "ヨガマット", "ダンベル", "フィットネストラッカー",
    ],
    "Pet Supplies": [
        "cat litter", "dog harness", "pet carrier", "pet bed", "pet water fountain",
        "katzenstreu", "hundegeschirr", "litière pour chat", "harnais pour chien",
        "arena para gatos", "arnés para perro", "lettiera per gatti", "guinzaglio per cani",
        "kattenbakvulling", "hondenharnas", "猫砂", "犬用ハーネス", "ペットベッド",
    ],
    "Toys & Gaming": [
        "board game", "lego set", "gaming headset", "action figure", "game controller",
        "brettspiel", "spielzeug", "jeu de société", "figurine", "juego de mesa",
        "figura de acción", "gioco da tavolo", "giocattolo", "bordspel", "speelgoed",
        "brädspel", "leksak", "ボードゲーム", "おもちゃ",
    ],
}

SHOPPING_TERMS = [
    "best", "review", "reviews", "buy", "deal", "price", "bestseller", "best seller", "best sellers",
    "product launch", "product review", "tested", "comparison", "versus", "new model", "unveiled",
    "kaufen", "test", "preis", "bestseller", "vergleich", "bewertung", "neuheit",
    "acheter", "avis", "prix", "comparatif", "nouveauté", "comprar", "reseña", "precio", "comparativa",
    "recensione", "prezzo", "confronto", "novità", "kopen", "prijs", "vergelijking", "köpa", "pris",
    "jämförelse", "おすすめ", "レビュー", "購入", "比較", "価格", "melhor", "avaliação", "teste",
]

QUERY_BY_LANGUAGE = {
    # Product nouns are intentionally concrete; generic retail and shopping-news queries
    # previously produced many irrelevant headlines.
    "en": '("wireless earbuds" OR "air fryer" OR "robot vacuum" OR "portable blender" OR "face serum" OR "running shoes" OR "dog harness" OR "board game") (review OR tested OR comparison OR "best" OR launch OR price)',
    "de": '(Heißluftfritteuse OR Saugroboter OR Kopfhörer OR Gesichtspflege OR Laufschuhe OR Hundegeschirr OR Brettspiel) (Test OR Vergleich OR Preis OR Bewertung OR Neuheit)',
    "fr": '("friteuse sans huile" OR "aspirateur robot" OR "écouteurs sans fil" OR "sérum visage" OR "chaussures de running" OR "harnais pour chien") (test OR comparatif OR prix OR avis OR nouveauté)',
    "es": '("freidora de aire" OR "aspiradora robot" OR "auriculares inalámbricos" OR "suero facial" OR "zapatillas de running" OR "arnés para perro") (prueba OR comparativa OR precio OR reseña OR novedad)',
    "it": '("friggitrice ad aria" OR "robot aspirapolvere" OR "auricolari wireless" OR "siero viso" OR "scarpe da running") (test OR confronto OR prezzo OR recensione OR novità)',
    "nl": '(airfryer OR robotstofzuiger OR koptelefoon OR gezichtsserum OR hardloopschoenen OR hondenharnas) (test OR vergelijking OR prijs OR review OR nieuw)',
    "sv": '(luftrenare OR hörlurar OR löparskor OR ryggsäck OR kattströ) (test OR jämförelse OR pris OR recension OR nyhet)',
    "ja": '(エアフライヤー OR ロボット掃除機 OR ワイヤレスイヤホン OR 美容液 OR スニーカー OR 猫砂) (レビュー OR 比較 OR 価格 OR 新商品)',
    "pt": '("fritadeira sem óleo" OR "aspirador robô" OR "fone sem fio" OR "sérum facial" OR "tênis de corrida") (teste OR comparação OR preço OR avaliação OR lançamento)',
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))
    return re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).strip()


def _has_phrase(normalized_title: str, term: str) -> bool:
    phrase = normalize(term)
    return bool(phrase and re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", normalized_title, flags=re.UNICODE))


def classify_product_coverage(title: str):
    normalized = normalize(title)
    matches = []
    category = None
    for name, terms in PRODUCT_TERMS.items():
        hits = [term for term in terms if _has_phrase(normalized, term)]
        if hits and category is None:
            category = name
        matches.extend(hits)
    if not matches:
        return None
    # Exclude broad editorial noise even when a product word appears incidentally.
    non_product_context = [
        "best selling books", "bestselling books", "book bestseller", "novel", "fiction books",
        "holiday shopping trends", "shopping trends", "retail sales", "retail market report",
        "consumer confidence", "store opening", "retailers", "gift guide", "gift ideas",
    ]
    if any(_has_phrase(normalized, term) for term in non_product_context):
        return None
    shopping_hits = [term for term in SHOPPING_TERMS if _has_phrase(normalized, term)]
    if not shopping_hits:
        return None
    score = min(90, 55 + min(15, (len(matches) - 1) * 5) + min(15, len(shopping_hits) * 5))
    return {
        "category": category,
        "matched_product_terms": matches[:6],
        "shopping_context_terms": shopping_hits[:5],
        "relevance_score": score,
        "confidence": "low",
        "signal_type": "editorial_product_coverage",
    }


def discover_product_articles(country: str, limit: int = 30):
    country = country.strip().upper()
    if country == "DZ":
        raise ValueError("DZ is excluded from ProfitBot target-market discovery")
    if country not in MARKET_LOCALES:
        raise ValueError("Unsupported target market")
    locale, language = MARKET_LOCALES[country]
    query = QUERY_BY_LANGUAGE.get(language, QUERY_BY_LANGUAGE["en"])
    params = urllib.parse.urlencode({"q": query, "hl": locale, "gl": country, "ceid": f"{country}:{language}"})
    url = "https://news.google.com/rss/search?" + params
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ProfitBot/1.0 (+https://github.com/aminechair5-lab/ProfitBot)",
                 "Accept": "application/rss+xml, application/xml"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = response.read(1_500_000)
        root = ET.fromstring(payload)
    except (urllib.error.URLError, TimeoutError, ET.ParseError) as exc:
        raise RuntimeError(f"Google News product feed unavailable: {str(exc)[:160]}") from exc

    items = []
    unclassified = []
    scanned = 0
    for node in root.findall(".//item")[:limit]:
        scanned += 1
        fields = {child.tag.split("}")[-1]: (child.text or "").strip() for child in node}
        title = fields.get("title", "")
        classification = classify_product_coverage(title)
        if not classification:
            if title and len(unclassified) < 8:
                unclassified.append({"title": title, "url": fields.get("link", "")})
            continue
        published = fields.get("pubDate")
        try:
            published_at = parsedate_to_datetime(published).isoformat() if published else None
        except (TypeError, ValueError):
            published_at = None
        items.append({
            "title": title,
            "source_url": fields.get("link", ""),
            "published_at": published_at,
            "source": "Google News RSS (localized product/editorial search)",
            "source_type": "editorial_coverage",
            "commercially_verified": False,
            "demand_verified": False,
            "sales_verified": False,
            **classification,
        })
    items.sort(key=lambda row: (row["relevance_score"], row.get("published_at") or ""), reverse=True)
    return {
        "geo": country,
        "source": "Google News RSS (localized product/editorial search)",
        "source_type": "editorial_coverage",
        "scanned_count": scanned,
        "matched_count": len(items),
        "unclassified_count": max(0, scanned - len(items)),
        "unclassified_items": unclassified,
        "items": items[:limit],
    }
