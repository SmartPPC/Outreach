"""Catalogue focus (the 80/20 best-sellers) and the checks that matter for them.

Rules from reviewing real audits:
- Only live ASINs with real sales count. Dead listings and tiny sellers are context, never findings.
- Long stockouts usually mean a discontinued line, so they're ignored. Only a live best-seller that
  keeps running out is a finding (lost sales).
- Wrong category, mixed variation families, duplicates and listing clutter are quick wins.
- Sponsored ranks on terms unrelated to the product point to wasted ad spend.
"""
from __future__ import annotations

import re
from collections import defaultdict

HERO_REVENUE_SHARE = 0.80
MAX_HERO_FAMILIES = 12
STOCKOUT_FLAG_RANGE = (10, 60)        # % of last 90 days; above 60 reads as discontinued
CROWDED_SELLERS = 5
DUPLICATE_SIMILARITY = 0.8

STOPWORDS = set("""a an and the for with of in on to by from at as is it this that your you our new
best pack set size ml g kg oz x pcs piece pieces count ct uk us edition""".split())
FOREIGN_WORDS = set("""und mit für fur der die das gesicht creme pflege avec pour le la les et sans
para con el los las y crema per il della""".split())

# Product types we can read from a title, and words a correct category leaf would contain.
# Extend for new verticals; anything unmatched is left to the skill's judgement.
PRODUCT_TYPES: list[tuple[str, tuple[str, ...]]] = [
    ("cleansing balm", ("cleans", "balm", "make-up remov", "makeup remov", "face wash")),
    ("cleansing oil", ("cleans", "oil", "make-up remov", "makeup remov", "face wash")),
    ("micellar water", ("cleans", "micellar", "make-up remov", "makeup remov")),
    ("cleanser", ("cleans", "face wash", "wash")),
    ("face wash", ("cleans", "face wash", "wash")),
    ("scrub", ("scrub", "exfoliat", "polish")),
    ("exfoliator", ("scrub", "exfoliat", "peel")),
    ("toner", ("toner", "tonic", "mist")),
    ("serum", ("serum", "treatment", "oil")),
    ("eye cream", ("eye",)),
    ("night cream", ("night", "moistur", "cream")),
    ("day cream", ("day", "moistur", "cream")),
    ("moisturiser", ("moistur", "cream", "lotion")),
    ("moisturizer", ("moistur", "cream", "lotion")),
    ("facial oil", ("oil", "serum", "moistur")),
    ("face mask", ("mask",)),
    ("sheet mask", ("mask",)),
    ("sunscreen", ("sun", "spf")),
    ("primer", ("primer", "foundation", "base")),
    ("foundation", ("foundation",)),
    ("lip balm", ("lip",)),
    ("shampoo", ("shampoo",)),
    ("conditioner", ("conditioner",)),
    ("body lotion", ("body", "lotion", "moistur")),
    ("body wash", ("body", "wash", "shower")),
    ("deodorant", ("deodorant", "antiperspirant")),
    ("supplement", ("supplement", "vitamin", "capsule", "tablet")),
]


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def tokens(s: str | None) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) > 2 and t not in STOPWORDS}


def stems(s: str | None) -> set[str]:
    """Crude stemming so 'cleansing' matches 'cleanser' and 'facial' matches 'facials'."""
    return {t[:5] for t in tokens(s)}


def product_type(title: str | None) -> str | None:
    t = (title or "").lower()
    for name, _ in PRODUCT_TYPES:
        if name in t:
            return name
    return None


def is_live(p: dict) -> bool:
    if p.get("available") is False or (p.get("sellers") == 0):
        return False
    return bool(p.get("price")) and bool((p.get("units_30d") or 0) > 0 or (p.get("revenue_30d") or 0) > 0)


# --- 80/20 ------------------------------------------------------------------------------------

def families(products: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for p in products:
        out[p.get("parent_asin") or p["asin"]].append(p)
    return out


def family_revenue(children: list[dict]) -> float:
    """Jungle Scout often repeats the parent's totals on every child: the same revenue, or the same
    units at each child's own price. Count the family once when it does."""
    revs = [c.get("revenue_30d") or 0 for c in children]
    units = [c.get("units_30d") or 0 for c in children]
    near_same_units = min(units) > 0 and max(units) <= min(units) * 1.15
    if len(children) > 1 and (len(set(revs)) == 1 or near_same_units):
        return sum(revs) / len(revs)
    return sum(revs)


def select_heroes(products: list[dict], share: float = HERO_REVENUE_SHARE,
                  max_families: int = MAX_HERO_FAMILIES) -> dict:
    live = [p for p in products if is_live(p)]
    fams = families(live)
    ranked = sorted(((parent, family_revenue(kids), kids) for parent, kids in fams.items()),
                    key=lambda r: r[1], reverse=True)
    total = sum(r[1] for r in ranked)
    heroes, covered = [], 0.0
    for parent, rev, kids in ranked:
        if total and covered / total >= share or len(heroes) >= max_families or rev <= 0:
            break
        lead = max(kids, key=lambda k: (k.get("units_30d") or 0, k.get("reviews") or 0))
        heroes.append({"parent_asin": parent, "asin": lead["asin"], "revenue_30d": round(rev),
                       "children": [k["asin"] for k in kids]})
        covered += rev
    return {
        "total_asins": len(products),
        "live_asins": len(live),
        "families": len(fams),
        "hero_families": len(heroes),
        "hero_revenue_share": round(covered / total, 2) if total else None,
        "est_monthly_revenue": round(total) if total else None,
        "heroes": heroes,
    }


# --- per-hero checks --------------------------------------------------------------------------

def category_mismatch(title: str, category_leaf: str | None) -> dict | None:
    ptype = product_type(title)
    if not ptype or not category_leaf:
        return None
    expected = dict(PRODUCT_TYPES)[ptype]
    leaf = category_leaf.lower()
    if any(word in leaf for word in expected):
        return None
    return {"product_type": ptype, "category": category_leaf}


def mixed_family(children: list[dict]) -> list[str] | None:
    """A variation family whose children are different products (e.g. balm + scrub + night cream)."""
    types = sorted({t for t in (product_type(c.get("title")) for c in children) if t})
    return types if len(types) > 1 else None


def seller_flags(p: dict, brand: str, brand_seller: str | None = None) -> list[str]:
    flags = []
    owner = p.get("buy_box_owner") or ""
    if owner and owner != brand_seller and "amazon" not in owner.lower() and norm(brand)[:6] not in norm(owner):
        flags.append(f"Buy Box held by {owner}")
    sellers = p.get("sellers") or p.get("offer_count")
    if sellers and sellers >= CROWDED_SELLERS:
        flags.append(f"{sellers} sellers on the listing")
    if p.get("price") and p.get("list_price") and p["price"] > p["list_price"] * 1.05:
        flags.append(f"selling above list price ({p['price']:.2f} vs {p['list_price']:.2f})")
    return flags


def stock_flag(p: dict) -> str | None:
    oos = p.get("oos_pct_90")
    lo, hi = STOCKOUT_FLAG_RANGE
    if oos is not None and lo <= oos <= hi:
        return f"out of stock {oos}% of the last 90 days"
    return None


def price_flag(p: dict) -> str | None:
    if p.get("price") and p.get("list_price") and p["price"] < p["list_price"] * 0.7:
        return f"discounted {100 - 100 * p['price'] / p['list_price']:.0f}% off list ({p['price']:.2f} vs {p['list_price']:.2f})"
    return None


# --- quick wins across live listings ----------------------------------------------------------

def _core_tokens(title: str, brand: str) -> set[str]:
    brand_toks = tokens(brand) | {norm(brand)}
    return {t for t in tokens(title) if t not in brand_toks and not re.fullmatch(r"\d+(ml|g|oz)?", t)}


def duplicates(live: list[dict], brand: str) -> list[list[dict]]:
    """Separate listings (different parents) for what reads as the same product."""
    groups: list[list[dict]] = []
    seen: set[str] = set()
    for i, a in enumerate(live):
        if a["asin"] in seen:
            continue
        ta, group = _core_tokens(a.get("title", ""), brand), [a]
        for b in live[i + 1:]:
            if b["asin"] in seen or (b.get("parent_asin") or b["asin"]) == (a.get("parent_asin") or a["asin"]):
                continue
            tb = _core_tokens(b.get("title", ""), brand)
            if ta and tb and len(ta & tb) / len(ta | tb) >= DUPLICATE_SIMILARITY:
                group.append(b)
        if len(group) > 1:
            seen.update(p["asin"] for p in group)
            groups.append([{"asin": p["asin"], "title": (p.get("title") or "")[:80],
                            "revenue_30d": p.get("revenue_30d")} for p in group])
    return groups


def clutter(live: list[dict], brand: str) -> list[dict]:
    b = norm(brand)
    spaced = (brand or "").lower()
    out = []
    for p in live:
        title = p.get("title") or ""
        issue = None
        if norm(title) == b:
            issue = "title is just the brand name"
        elif len(tokens(title) & FOREIGN_WORDS) >= 2:
            issue = "title not in the marketplace language"
        elif b and b not in norm(title):
            issue = "brand name missing from title"
        elif spaced and " " in spaced and spaced not in title.lower():
            issue = "brand name spelled inconsistently"
        if issue:
            out.append({"asin": p["asin"], "title": title[:80], "issue": issue})
    return out


# --- ads --------------------------------------------------------------------------------------

def wasted_terms(hero_title: str, brand: str, keywords: list[dict]) -> list[dict]:
    """Terms the hero is sponsored on but has no organic relevance to: auto/broad drift."""
    title_stems = stems(hero_title) - stems(brand)  # "facialist" must not make "facial oil" relevant
    brand_toks = tokens(brand)
    out = []
    for k in keywords:
        if not k.get("sponsored_rank") or (k.get("organic_rank") or 999) <= 100:
            continue
        kt = tokens(k["keyword"])
        nk, nb = norm(k["keyword"]), norm(brand)
        partial_brand = bool(nk) and nk != nb and ((kt and kt <= brand_toks) or nb.startswith(nk))
        if partial_brand or not (stems(k["keyword"]) & title_stems):
            out.append({"keyword": k["keyword"], "volume": k.get("volume"), "sponsored_rank": k["sponsored_rank"],
                        "reason": "partial brand term" if partial_brand else "unrelated to the product"})
    return sorted(out, key=lambda r: r.get("volume") or 0, reverse=True)
