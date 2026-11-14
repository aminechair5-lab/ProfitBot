import re

# Phrase-aware catalog with English, Arabic, and French terms. These are
# candidate-discovery signals, not proof of demand, sales, or profitability.
PRODUCT_CATALOG = {
    "Electronics": [
        "iphone", "smartphone", "mobile phone", "phone case", "phone charger",
        "wireless charger", "power bank", "headphones", "earbuds", "bluetooth speaker",
        "smartwatch", "laptop", "tablet", "keyboard", "computer mouse", "monitor",
        "digital camera", "projector", "gaming console", "game controller",
        "هاتف ذكي", "هاتف", "ايفون", "آيفون", "شاحن", "سماعات", "سماعات لاسلكية",
        "بطارية متنقلة", "حاسوب", "كمبيوتر", "ساعة ذكية", "لوحة مفاتيح",
        "téléphone", "chargeur", "écouteurs", "batterie externe", "ordinateur",
        "montre connectée", "clavier"
    ],
    "Home & Kitchen": [
        "air fryer", "coffee maker", "espresso machine", "vacuum cleaner",
        "robot vacuum", "water bottle", "storage organizer", "drawer organizer",
        "desk lamp", "led lamp", "office chair", "mattress", "pillow", "cookware",
        "kitchen gadget", "blender", "frying pan", "pressure cooker",
        "قلاية هوائية", "مقلاة هوائية", "آلة قهوة", "ماكينة قهوة", "مكنسة كهربائية",
        "مكنسة روبوت", "قارورة ماء", "مصباح", "كرسي مكتب", "مرتبة", "وسادة",
        "friteuse sans huile", "cafetière", "aspirateur", "gourde", "lampe",
        "chaise de bureau", "matelas"
    ],
    "Beauty & Personal Care": [
        "skin care", "skincare", "face serum", "moisturizer", "sunscreen",
        "makeup", "hair dryer", "hair straightener", "electric shaver",
        "perfume", "beauty device",
        "العناية بالبشرة", "سيروم", "مرطب", "واقي الشمس", "مكياج",
        "مجفف شعر", "مملس شعر", "عطر",
        "soin de la peau", "sérum visage", "crème hydratante", "crème solaire",
        "maquillage", "sèche cheveux", "parfum"
    ],
    "Fashion & Accessories": [
        "sneakers", "running shoes", "boots", "backpack", "handbag", "wallet",
        "sunglasses", "smart ring", "jacket", "dress", "jeans", "wristwatch",
        "necklace", "bracelet",
        "حذاء رياضي", "أحذية رياضية", "حقيبة", "محفظة", "نظارات شمسية",
        "سترة", "فستان", "ساعة يد", "قلادة",
        "baskets", "chaussures de sport", "sac à dos", "sac à main",
        "portefeuille", "lunettes de soleil", "veste", "robe", "montre"
    ],
    "Sports & Fitness": [
        "yoga mat", "resistance bands", "dumbbells", "treadmill",
        "fitness tracker", "waterproof bag", "camping tent", "hiking shoes",
        "بساط يوغا", "أشرطة مقاومة", "أثقال", "جهاز مشي", "خيمة",
        "tapis de yoga", "bandes de résistance", "haltères", "tapis de course",
        "tente de camping"
    ],
    "Pet Supplies": [
        "pet carrier", "cat litter", "dog harness", "pet toy", "pet bed",
        "حاملة حيوانات", "رمل القطط", "طوق كلب", "لعبة قطط",
        "litière pour chat", "harnais pour chien"
    ],
    "Toys & Gaming": [
        "lego set", "board game", "action figure", "toy", "gaming headset",
        "لعبة أطفال", "ألعاب أطفال", "سماعة ألعاب", "لعبة تركيب",
        "jeu de société", "figurine", "jouet", "casque gaming"
    ],
}

SHOPPING_INTENT = [
    "buy", "best", "review", "price", "deal", "discount", "sale",
    "where to buy", "versus", "vs", "شراء", "اشتري", "سعر", "أسعار",
    "أفضل", "افضل", "مراجعة", "تخفيض", "تخفيضات", "عرض", "عروض",
    "acheter", "meilleur", "meilleure", "prix", "avis", "promotion",
    "promotions", "réduction"
]

NON_COMMERCIAL = [
    "breaking news", "election", "president", "prime minister",
    "football", "soccer", "basketball", "tennis", "cricket", "match result",
    "live score", "weather", "earthquake", "war", "death", "obituary",
    "celebrity", "actor", "actress", "singer", "concert", "movie", "film",
    "tv series", "episode", "championship", "tournament",
    "أخبار عاجلة", "انتخابات", "رئيس", "رئيس الوزراء", "كرة القدم",
    "كرة السلة", "كرة اليد", "مباراة", "نتيجة المباراة", "طقس", "أحوال الطقس",
    "زلزال", "حرب", "وفاة", "ممثل", "ممثلة", "مغني", "مسلسل", "فيلم",
    "actualité", "élection", "président", "météo", "tremblement de terre",
    "guerre", "décès", "acteur", "actrice", "chanteur", "film", "série"
]


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(re.search(r"(?<!\\w)" + re.escape(phrase) + r"(?!\\w)", text))


def classify_trend_title(title: str):
    """Return a multilingual product-candidate classification or None."""
    normalized = re.sub(r"[^\\w]+", " ", title.casefold(), flags=re.UNICODE).strip()
    matched = []
    categories = []
    for category, terms in PRODUCT_CATALOG.items():
        category_hits = [term for term in terms if _contains_phrase(normalized, term.casefold())]
        if category_hits:
            categories.append(category)
            matched.extend(category_hits)

    blocked = [term for term in NON_COMMERCIAL if _contains_phrase(normalized, term.casefold())]
    if not matched or blocked:
        return None

    intent_hits = [term for term in SHOPPING_INTENT if _contains_phrase(normalized, term.casefold())]
    score = min(95, 58 + min(18, (len(matched) - 1) * 9) + min(15, len(intent_hits) * 5))
    reasons = ["تطابق مع كلمات منتج معروفة"]
    if len(matched) > 1:
        reasons.append("أكثر من مصطلح منتج")
    if intent_hits:
        reasons.append("وجود نية شراء أو مقارنة")
    return {
        "category": categories[0],
        "matched_product_terms": matched[:6],
        "shopping_intent_terms": intent_hits,
        "commercial_score": score,
        "confidence": "medium" if score >= 70 else "low",
        "classification_reasons": reasons,
    }
