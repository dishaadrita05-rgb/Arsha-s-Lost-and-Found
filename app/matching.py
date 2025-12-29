# app/matching.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime

# Optional: sklearn TF-IDF retrieval (nice to have, but should NOT crash if missing)
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    _HAS_SKLEARN = True
except Exception:
    TfidfVectorizer = None
    cosine_similarity = None
    _HAS_SKLEARN = False

from .nlp import tokenize, loads_extracted


@dataclass
class MatchResult:
    other_id: int
    score: float
    reasons: List[str]


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a.intersection(b))
    union = len(a.union(b))
    return inter / union if union else 0.0


def parse_iso(dt: Optional[str]) -> Optional[datetime]:
    if not dt:
        return None
    try:
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except Exception:
        return None


def time_plausibility(lost_time: Optional[str], found_time: Optional[str]) -> Tuple[float, Optional[str]]:
    """
    Returns (score, reason)
    - Prefer found AFTER lost, within a few days.
    """
    lt = parse_iso(lost_time)
    ft = parse_iso(found_time)
    if not lt or not ft:
        return 0.0, None

    delta_hours = (ft - lt).total_seconds() / 3600.0
    if delta_hours < -1:
        return -0.15, "Time seems inconsistent (found before lost)."
    if 0 <= delta_hours <= 72:
        return 0.15, f"Time plausible: found ~{delta_hours:.1f}h after lost."
    if 72 < delta_hours <= 240:
        return 0.05, f"Time plausible but wide gap (~{delta_hours/24:.1f} days)."
    return 0.0, None


def compute_match(a: Dict[str, Any], b: Dict[str, Any]) -> MatchResult:
    """
    a = current report row dict
    b = candidate opposite report row dict
    """
    a_text = f"{a.get('title','')} {a.get('description','')} {a.get('location_text','')}"
    b_text = f"{b.get('title','')} {b.get('description','')} {b.get('location_text','')}"

    a_tokens = set(tokenize(a_text))
    b_tokens = set(tokenize(b_text))

    text_sim = jaccard(a_tokens, b_tokens)

    a_ex = loads_extracted(a.get("extracted_json") or "{}")
    b_ex = loads_extracted(b.get("extracted_json") or "{}")

    reasons: List[str] = []
    score = 0.0

    # Weighted parts
    score += 0.55 * text_sim
    if text_sim > 0.15:
        reasons.append(f"Text overlap looks similar (Jaccard {text_sim:.2f}).")

    # item type
    if a_ex.get("item_type") and b_ex.get("item_type"):
        if a_ex["item_type"] == b_ex["item_type"]:
            score += 0.20
            reasons.append(f"Item type matches: {a_ex['item_type']}.")
        else:
            score -= 0.05
            reasons.append(f"Item type differs ({a_ex['item_type']} vs {b_ex['item_type']}).")

    # colors
    a_colors = set(a_ex.get("colors") or [])
    b_colors = set(b_ex.get("colors") or [])
    if a_colors and b_colors:
        overlap = a_colors.intersection(b_colors)
        if overlap:
            score += 0.12
            reasons.append(f"Color overlap: {', '.join(sorted(overlap))}.")
        else:
            score -= 0.03
            reasons.append("Colors don’t overlap.")

    # brand
    if a_ex.get("brand") and b_ex.get("brand"):
        if a_ex["brand"] == b_ex["brand"]:
            score += 0.12
            reasons.append(f"Brand matches: {a_ex['brand']}.")
        else:
            score -= 0.02

    # location token overlap (cheap)
    a_loc = set(tokenize(a.get("location_text", "")))
    b_loc = set(tokenize(b.get("location_text", "")))
    loc_sim = jaccard(a_loc, b_loc)
    score += 0.10 * loc_sim
    if loc_sim > 0.20:
        reasons.append(f"Location text seems close (Jaccard {loc_sim:.2f}).")

    # time plausibility (lost vs found)
    if a.get("kind") == "lost":
        tscore, treason = time_plausibility(a.get("event_time"), b.get("event_time"))
    else:
        tscore, treason = time_plausibility(b.get("event_time"), a.get("event_time"))
    score += tscore
    if treason:
        reasons.append(treason)

    # identifier hashes overlap (privacy-safe)
    a_ids = set(a_ex.get("identifiers") or [])
    b_ids = set(b_ex.get("identifiers") or [])
    if a_ids and b_ids and a_ids.intersection(b_ids):
        score += 0.35
        reasons.append("Hidden identifier signal matches (not displayed).")

    # clamp-ish
    score = max(-0.5, min(1.5, score))

    return MatchResult(other_id=int(b["id"]), score=float(score), reasons=reasons)


def retrieve_candidates_tfidf(current: Dict[str, Any], candidates: List[Dict[str, Any]], top_n: int = 200) -> List[Dict[str, Any]]:
    """
    If sklearn is available, use TF-IDF to shortlist candidates.
    Otherwise, return a simple slice so the app still runs everywhere.
    """
    if not candidates:
        return []

    if not _HAS_SKLEARN:
        return candidates[: min(top_n, len(candidates))]

    cur_text = f"{current.get('title','')} {current.get('description','')} {current.get('location_text','')}"
    cand_texts = [f"{c.get('title','')} {c.get('description','')} {c.get('location_text','')}" for c in candidates]

    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
    X = vectorizer.fit_transform([cur_text] + cand_texts)
    sims = cosine_similarity(X[0:1], X[1:]).flatten()

    idx = sims.argsort()[::-1][: min(top_n, len(candidates))]
    return [candidates[i] for i in idx]


def rank_matches(current: Dict[str, Any], candidates: List[Dict[str, Any]], k: int = 5) -> List[MatchResult]:
    short = retrieve_candidates_tfidf(current, candidates, top_n=200)
    scored = [compute_match(current, c) for c in short]
    scored.sort(key=lambda m: m.score, reverse=True)
    return scored[:k]


def choose_clarifying_question(current: Dict[str, Any], top_candidates: List[Dict[str, Any]]) -> Optional[Tuple[str, str]]:
    """
    Pick ONE question that best separates the top candidates, preferring fields missing in current report.
    Returns (key, question_text) or None.
    """
    cur_ex = loads_extracted(current.get("extracted_json") or "{}")

    fields = [
        ("brand", "What brand is it? (e.g., Samsung, Apple, Xiaomi)"),
        ("colors", "What color is it? (e.g., black/blue/red/transparent)"),
        ("item_type", "What is the item type? (phone/wallet/keys/bag/umbrella/etc.)"),
        ("unique_marks", "Any unique mark? (sticker / scratch / engraved text)"),
    ]

    fields = [(k, q) for (k, q) in fields if not cur_ex.get(k)]
    if not fields or not top_candidates:
        return None

    best_key = None
    best_q = None
    best_diversity = -1

    for key, question in fields:
        values = set()
        for c in top_candidates:
            ex = loads_extracted(c.get("extracted_json") or "{}")
            v = ex.get(key)
            if isinstance(v, list):
                v = tuple(v)
            if v:
                values.add(v)
        diversity = len(values)
        if diversity > best_diversity:
            best_diversity = diversity
            best_key = key
            best_q = question

    if best_key and best_diversity >= 2:
        return best_key, best_q
    return None


# ✅ This is the missing function your main.py is importing
def explain_match(a: Dict[str, Any], b: Dict[str, Any]) -> str:
    """
    Returns a human-readable explanation string for why two reports match.
    (Some versions of main.py expect this function.)
    """
    m = compute_match(a, b)
    if not m.reasons:
        return "No strong signals; mostly general text similarity."
    return " • ".join(m.reasons)
