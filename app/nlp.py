# app/nlp.py
from __future__ import annotations

import hashlib
import json
import re
from typing import Dict, Any, List, Optional


# -----------------------------
# Color detection
# -----------------------------

# Canonical base colors (lowercase)
BASE_COLORS = {
    "black", "white", "gray", "red", "blue", "green", "yellow", "orange",
    "pink", "purple", "brown",
    "silver", "gold", "navy", "maroon",
    "beige", "cream", "ivory", "tan", "khaki",
    "teal", "turquoise", "cyan", "aqua",
    "magenta", "lavender", "violet", "indigo",
    "lime", "mint", "olive",
    "burgundy", "peach", "mustard",
    "bronze", "copper",
    "charcoal",
}

# Aliases -> canonical
COLOR_ALIASES = {
    "grey": "gray",
    "offwhite": "off white",
    "off-white": "off white",
    "offwhitee": "off white",  # common typo
    "golden": "gold",
    "bluish": "blue",
    "reddish": "red",
    "greenish": "green",
    "pinkish": "pink",
    "purplish": "purple",
    "violetish": "violet",
    "transparent": "transparent",
    "clear": "transparent",
    "translucent": "transparent",
    "seethrough": "transparent",
    "see-through": "transparent",
}

# e.g., "light blue", "dark-red"
SHADE_RE = re.compile(
    r"\b(light|dark|deep|pale|bright|neon)\s+"
    r"(black|white|gray|grey|red|blue|green|yellow|orange|pink|purple|brown|navy|maroon|"
    r"beige|cream|ivory|tan|khaki|teal|turquoise|cyan|aqua|magenta|lavender|violet|indigo|"
    r"lime|mint|olive|burgundy|peach|mustard|silver|gold|bronze|copper|charcoal)\b"
)

# e.g., "lightblue", "darkgreen"
SHADE_JOINED_RE = re.compile(
    r"\b(light|dark|deep|pale|bright|neon)"
    r"(black|white|gray|grey|red|blue|green|yellow|orange|pink|purple|brown|navy|maroon|"
    r"beige|cream|ivory|tan|khaki|teal|turquoise|cyan|aqua|magenta|lavender|violet|indigo|"
    r"lime|mint|olive|burgundy|peach|mustard|silver|gold|bronze|copper|charcoal)\b"
)

# Special multi-word colors
SPECIAL_COLOR_PHRASES = {
    "rose gold": ("rose gold", ["gold"]),
    "space gray": ("space gray", ["gray"]),
    "space grey": ("space gray", ["gray"]),
    "off white": ("off white", ["white"]),
    "see through": ("transparent", []),
    "see-through": ("transparent", []),
}


def _canon_color(s: str) -> str:
    s = s.strip().lower()
    if s in COLOR_ALIASES:
        return COLOR_ALIASES[s]
    return s


def extract_colors(text: str, tokens: List[str], norm: str) -> List[str]:
    colors: set[str] = set()

    # Special phrases
    for phrase, (canon, also) in SPECIAL_COLOR_PHRASES.items():
        if phrase in norm:
            colors.add(canon)
            for c in also:
                colors.add(c)

    # "light blue" etc
    for m in SHADE_RE.finditer(norm):
        shade = m.group(1)
        base = _canon_color(m.group(2))
        phrase = f"{shade} {base}"
        colors.add(phrase)
        colors.add(base)

    # "lightblue" etc
    for m in SHADE_JOINED_RE.finditer(norm.replace("-", "")):
        shade = m.group(1)
        base = _canon_color(m.group(2))
        phrase = f"{shade} {base}"
        colors.add(phrase)
        colors.add(base)

    # Token-level colors
    for t in tokens:
        ct = _canon_color(t)
        if ct in BASE_COLORS:
            colors.add(ct)
        if ct in ("transparent", "off white"):
            colors.add(ct)

    return sorted(colors)


# -----------------------------
# Item detection + synonym expansion
# -----------------------------

ITEM_SYNONYMS: Dict[str, set[str]] = {
    "phone": {
        "phone", "phones",
        "mobile", "mobiles",
        "cell", "cellphone", "cellphones", "cell-phone", "cell-phones",
        "smartphone", "smartphones",
        "handset", "handsets",
        "iphone", "iphones",
        "android",
    },
    "laptop": {
        "laptop", "laptops",
        "notebook", "notebooks",
        "macbook", "macbooks",
        "ultrabook", "ultrabooks",
    },
    "tablet": {
        "tablet", "tablets",
        "ipad", "ipads",
        "tab", "tabs",
    },
    "earbuds": {
        "earbud", "earbuds",
        "earphone", "earphones",
        "earpiece", "earpieces",
        "airpod", "airpods",
        "headset", "headsets",
        "tws",
        "buds",
    },
    "headphones": {
        "headphone", "headphones",
        "head-set", "head-sets",
        "headset", "headsets",
    },
    "powerbank": {
        "powerbank", "power-bank", "powerbanks", "power-banks",
    },
    "charger": {
        "charger", "chargers",
        "adapter", "adaptor", "adapters", "adaptors",
        "charging", "charge",
        "cable", "cables",
        "wire", "wires",
        "typec", "type-c", "usbc", "usb-c",
        "microusb", "micro-usb",
        "lightning",
    },
    "usb": {
        "usb", "pendrive", "pen-drive", "flashdrive", "flash-drive",
        "thumbdrive", "thumb-drive",
        "sdcard", "sd-card", "microsd",
        "memorycard", "memory-card",
    },
    "camera": {
        "camera", "cameras",
        "gopro", "dslr",
        "nikon", "canon",
        "tripod", "tripods",
    },
    "wallet": {
        "wallet", "wallets",
        "purse", "purses",
        "billfold", "billfolds",
        "cardholder", "card-holder", "cardholders", "card-holders",
        "moneybag", "money-bag", "moneybags",
    },
    "bag": {
        "bag", "bags",
        "backpack", "backpacks",
        "rucksack", "rucksacks",
        "handbag", "handbags",
        "satchel", "satchels",
        "pouch", "pouches",
        "luggage", "suitcase", "suitcases",
    },
    "keys": {
        "key", "keys",
        "keychain", "keychains",
        "keyring", "keyrings",
    },
    "card": {
        "card", "cards",
        "id", "nid",
        "studentid", "student-id",
        "license", "licence",
        "bankcard", "bank-card",
        "atm", "debit", "credit",
    },
    "documents": {
        "document", "documents",
        "paper", "papers",
        "file", "files",
        "certificate", "certificates",
        "passport", "passports",
        "ticket", "tickets",
        "receipt", "receipts",
        "letter", "letters",
    },
    "umbrella": {
        "umbrella", "umbrellas",
        "parasol", "parasols",
    },
    "fan": {
        "fan", "fans",
        "pocketfan", "pocket-fan", "pocketfans",
        "minifan", "mini-fan", "minifans",
        "handfan", "hand-fan", "handfans",
        "portablefan", "portable-fan",
    },
    "book": {
        "book", "books",
        "notebook", "notebooks",
        "textbook", "textbooks",
        "novel", "novels",
        "diary", "diaries",
        "journal", "journals",
        "copy", "copies",
        "khata", "khatas",
    },
    "bottle": {
        "bottle", "bottles",
        "waterbottle", "water-bottle",
        "flask", "flasks",
        "thermos", "sipper",
    },
    "glasses": {
        "glasses", "spectacles", "goggles",
        "sunglass", "sunglasses",
        "specs",
    },
    "jewelry": {
        "ring", "rings",
        "necklace", "necklaces",
        "bracelet", "bracelets",
        "chain", "chains",
        "earring", "earrings",
        "jewelry", "jewellery",
    },
    "money": {
        "money", "cash", "tk", "taka",
        "note", "notes",
        "coin", "coins",
    },
    "clothing": {
        "jacket", "jackets",
        "coat", "coats",
        "hoodie", "hoodies",
        "sweater", "sweaters",
        "shirt", "shirts",
        "tshirt", "t-shirt", "tshirts", "t-shirts",
        "pant", "pants", "trouser", "trousers",
        "scarf", "scarves",
        "cap", "caps", "hat", "hats",
        "mask", "masks",
    },
    "calculator": {
        "calculator", "calculators",
        "casio",
    },
    "watch": {
        "watch", "watches",
        "smartwatch", "smartwatches",
        "band", "bands",
    },
}

ITEM_PHRASES: Dict[str, set[str]] = {
    "powerbank": {"power bank", "powerbank", "power-bank"},
    "charger": {
        "phone charger", "mobile charger", "laptop charger",
        "charging cable", "charger cable",
        "type c cable", "type-c cable", "usb c cable", "usb-c cable",
        "micro usb cable", "micro-usb cable",
        "lightning cable",
    },
    "card": {"id card", "student id", "student-id", "nid card", "atm card", "bank card"},
    "usb": {"usb drive", "flash drive", "flash-drive", "pen drive", "pen-drive", "memory card", "sd card"},
    "earbuds": {"bluetooth earphone", "wireless earphone", "true wireless", "tws earbud", "tws earbuds"},
    "fan": {"pocket fan", "mini fan", "hand fan", "portable fan"},
    "book": {"exercise book", "text book", "textbook", "note book", "note-book"},
    "documents": {"national id", "nid card", "birth certificate", "exam admit", "admit card"},
}

TOKEN_CANONICAL_MAP: Dict[str, str] = {}
for _canon, _syns in ITEM_SYNONYMS.items():
    for _t in _syns:
        TOKEN_CANONICAL_MAP[_t] = _canon


def infer_item_type(text: str, tokens: List[str], norm: str) -> Optional[str]:
    token_set = set(tokens)
    scores: Dict[str, int] = {k: 0 for k in ITEM_SYNONYMS.keys()}

    for itype, phrases in ITEM_PHRASES.items():
        for p in phrases:
            if p in norm:
                scores[itype] = scores.get(itype, 0) + 3

    for itype, syns in ITEM_SYNONYMS.items():
        scores[itype] = scores.get(itype, 0) + len(token_set.intersection(syns))

    best_type = None
    best_score = 0
    preference = [
        "documents",
        "card",
        "wallet",
        "keys",
        "phone",
        "laptop",
        "tablet",
        "earbuds",
        "headphones",
        "powerbank",
        "charger",
        "usb",
        "camera",
        "umbrella",
        "fan",
        "book",
        "glasses",
        "bottle",
        "jewelry",
        "money",
        "watch",
        "calculator",
        "bag",
        "clothing",
    ]
    pref_rank = {k: i for i, k in enumerate(preference)}

    for itype, sc in scores.items():
        if sc > best_score:
            best_type = itype
            best_score = sc
        elif sc == best_score and sc > 0:
            if pref_rank.get(itype, 10_000) < pref_rank.get(best_type or "", 10_000):
                best_type = itype

    return best_type if best_score > 0 else None


# -----------------------------
# Tokenization / normalization
# -----------------------------

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "with", "without", "near", "at", "in", "on", "to", "from",
    "of", "for", "my", "our", "your", "is", "was", "were", "it", "this", "that", "i", "we", "they",
    "yesterday", "today", "tomorrow", "evening", "morning", "night",
    "lost", "found", "missing", "pickup", "pick", "picked", "drop", "dropped",
}

COMMON_BRANDS = {
    "apple", "iphone", "ipad",
    "samsung", "xiaomi", "redmi", "poco", "oneplus", "oppo", "vivo", "huawei",
    "google", "pixel", "nokia", "realme", "motorola", "infinix", "tecno", "itel",
    "dell", "hp", "lenovo", "asus", "acer", "msi", "macbook", "microsoft", "surface",
    "sony", "jbl", "bose", "beats", "skullcandy", "sennheiser",
    "anker", "soundcore", "baseus", "ugreen", "aukey", "romoss",
    "boat", "edifier",
    "casio", "fossil", "garmin",
}


def normalize_text(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[\r\n\t]+", " ", s)
    s = re.sub(r"[^a-z0-9\s\-]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokenize(s: str) -> List[str]:
    s = normalize_text(s)
    raw = [t for t in s.split(" ") if t]
    out: List[str] = []
    for t in raw:
        for part in t.split("-"):
            part = part.strip()
            if not part:
                continue
            if part in STOPWORDS:
                continue
            out.append(part)
    return out


def expand_tokens(tokens: List[str]) -> List[str]:
    expanded = list(tokens)
    for t in tokens:
        canon = TOKEN_CANONICAL_MAP.get(t)
        if canon and canon not in expanded:
            expanded.append(canon)

        ct = _canon_color(t)
        if ct != t and ct not in expanded:
            expanded.append(ct)

    if "see" in tokens and "through" in tokens and "transparent" not in expanded:
        expanded.append("transparent")

    seen = set()
    uniq: List[str] = []
    for t in expanded:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


# -----------------------------
# Identifier extraction (privacy-safe)
# -----------------------------

def dumps_extracted(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False)


def loads_extracted(s: str) -> Dict[str, Any]:
    try:
        return json.loads(s)
    except Exception:
        return {}


def _hash_id(value: str) -> str:
    h = hashlib.sha256(("LFv1:" + value).encode("utf-8")).hexdigest()
    return h[:16]


EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[\w.\-]+\.[A-Za-z]{2,}\b")
BD_PHONE_RE = re.compile(r"\b(?:\+?880)?01\d{9}\b")
LONG_DIGITS_RE = re.compile(r"\b\d{10,20}\b")


def extract_identifiers(text: str) -> List[str]:
    norm = normalize_text(text)
    ids: List[str] = []

    for m in EMAIL_RE.finditer(text or ""):
        ids.append("email:" + m.group(0).lower())

    compact = (norm or "").replace(" ", "").replace("-", "")
    for m in BD_PHONE_RE.finditer(compact):
        ids.append("phone:" + m.group(0))

    for m in LONG_DIGITS_RE.finditer(norm or ""):
        ids.append("num:" + m.group(0))

    return sorted({_hash_id(x) for x in ids})


def mask_sensitive(text: str) -> str:
    text = text or ""

    def _mask_email(m):
        s = m.group(0)
        user, domain = s.split("@", 1)
        if len(user) <= 2:
            mu = "*" * len(user)
        else:
            mu = user[:1] + "*" * (len(user) - 2) + user[-1:]
        return mu + "@" + domain

    text = EMAIL_RE.sub(_mask_email, text)

    def _mask_phone(m):
        s = m.group(0)
        digits = re.sub(r"\D+", "", s)
        if len(digits) <= 2:
            return "*" * len(digits)
        return ("*" * (len(digits) - 2)) + digits[-2:]

    text = BD_PHONE_RE.sub(_mask_phone, text)
    text = LONG_DIGITS_RE.sub("[REDACTED_ID]", text)
    return text


# -----------------------------
# Main extraction
# -----------------------------

def extract(report_text: str) -> Dict[str, Any]:
    norm = normalize_text(report_text)
    tokens = tokenize(report_text)
    tokens = expand_tokens(tokens)

    identifiers = extract_identifiers(report_text)
    colors = extract_colors(report_text, tokens, norm)

    brands = sorted({t for t in tokens if t in COMMON_BRANDS})
    brand = brands[0] if brands else None

    item_type = infer_item_type(report_text, tokens, norm)

    # ensure canonical type appears as a token (helps matching across wording)
    if item_type and item_type not in tokens:
        tokens.append(item_type)

    unique_marks: List[str] = []
    mark_words = [
        ("sticker", {"sticker", "stickers"}),
        ("scratch", {"scratch", "scratched", "scratches"}),
        ("engraved", {"engraved", "engraving", "etched"}),
        ("crack", {"crack", "cracked", "broken"}),
        ("tear", {"tear", "torn"}),
        ("dent", {"dent", "dented"}),
        ("lock", {"lock", "locked"}),
    ]
    token_set = set(tokens)
    for canon, syns in mark_words:
        if token_set.intersection(syns):
            unique_marks.append(canon)

    contained: List[str] = []
    m = re.search(r"\bcontains\b(.+)$", norm)
    if m:
        contained = [x.strip() for x in m.group(1).split(",") if x.strip()]

    return {
        "tokens": tokens,
        "item_type": item_type,
        "colors": colors,
        "brand": brand,
        "unique_marks": sorted(set(unique_marks)),
        "contained": contained,
        "identifiers": identifiers,
    }


def apply_clarification(extracted: Dict[str, Any], key: str, answer: str) -> Dict[str, Any]:
    extracted = dict(extracted or {})
    ans_tokens = expand_tokens(tokenize(answer))
    norm = normalize_text(answer)

    existing = extracted.get("tokens") or []
    if not isinstance(existing, list):
        existing = []
    extracted["tokens"] = expand_tokens([*existing, *ans_tokens])

    if key == "brand":
        brands = [t for t in ans_tokens if t in COMMON_BRANDS]
        extracted["brand"] = brands[0] if brands else (ans_tokens[0] if ans_tokens else answer.strip().lower())

    elif key == "colors":
        extracted["colors"] = extract_colors(answer, ans_tokens, norm)

    elif key == "item_type":
        itype = infer_item_type(answer, ans_tokens, norm)
        extracted["item_type"] = itype or (ans_tokens[0] if ans_tokens else None)

    elif key == "unique_marks":
        marks = []
        s = " ".join(ans_tokens)
        if "sticker" in s:
            marks.append("sticker")
        if "scratch" in s:
            marks.append("scratch")
        if "engraved" in s or "etch" in s:
            marks.append("engraved")
        if "crack" in s or "broken" in s:
            marks.append("crack")
        if "tear" in s or "torn" in s:
            marks.append("tear")
        extracted["unique_marks"] = sorted(set(marks))

    # if item_type is set, keep it in tokens
    it = extracted.get("item_type")
    if it and isinstance(extracted.get("tokens"), list) and it not in extracted["tokens"]:
        extracted["tokens"].append(it)

    return extracted
