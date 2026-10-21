"""Merge a run's collector output into one dataset.json the skill reasons over.

Everything numeric is computed here, deterministically, so the skill's write-up only interprets.
Assumptions used for estimates are written into the dataset so they can be shown on the audit page.
"""
from __future__ import annotations

import datetime as dt
import re
import statistics
from collections import defaultdict
from pathlib import Path

from collectors.common import MARKETPLACES, ROOT, RUNS_DIR, read_json

from . import checks, mobile
from .rubric import check_listing

# --- assumptions (surfaced on the audit page) -------------------------------------------------
CLICKS_PER_SEARCH = {"low": 0.08, "mid": 0.12, "high": 0.20}   # share of searches producing an ad click
TARGET_SPONSORED_SOV = {"brand": 0.50, "core": 0.20, "category": 0.10, "long_tail": 0.15, "competitor": 0.05}
AD_TYPE_SPLIT = {
    "brand": {"SP": 0.5, "SB": 0.5},
    "core": {"SP": 0.6, "SB": 0.2, "SBV": 0.2},
    "category": {"SP": 0.5, "SB": 0.25, "SBV": 0.25},
    "long_tail": {"SP": 1.0},
    "competitor": {"SP": 0.6, "SD": 0.4},
}
TOP_OF_PAGE, PAGE_ONE, PAGE_TWO = 4, 20, 60
CONSUMABLE_CATEGORIES = re.compile(
    r"beauty|health|grocery|food|pet|baby|household|personal care|drugstore|vitamin|supplement|"
    r"cleaning|coffee|tea|snack|beverage|cosmetic|skin|hair|oral", re.I)
MULTIPACK = re.compile(r"\bpack of\b|\b\d+\s*[x×]\b|\b\d+[- ]pack\b|\bset of\b|\bbundle\b|\bmulti-?pack\b", re.I)


# --- helpers used during collection ----------------------------------------------------------

def _revenue_proxy(p: dict) -> float:
    if p.get("monthly_sold") and p.get("price"):
        return p["monthly_sold"] * p["price"]
    return 1e6 / p["sales_rank"] if p.get("sales_rank") else 0.0


def top_parents(products: list[dict], n: int) -> list[str]:
    """Best-selling child ASIN of each of the top-n parents (keyword tools want a live child)."""
    best: dict[str, dict] = {}
    for p in products:
        parent = p.get("parent_asin") or p["asin"]
        if parent not in best or _revenue_proxy(p) > _revenue_proxy(best[parent]):
            best[parent] = p
    ranked = sorted(best.values(), key=_revenue_proxy, reverse=True)
    return [p["asin"] for p in ranked[:n]]


def merge_keywords(rows: list[dict]) -> list[dict]:
    """Dedupe keywords across ASINs/sources: best rank, max volume, first known bid/relevancy."""
    merged: dict[str, dict] = {}
    for r in rows:
        kw = (r.get("keyword") or "").strip().lower()
        if not kw:
            continue
        m = merged.setdefault(kw, {**r, "keyword": kw})
        for rank in ("organic_rank", "sponsored_rank"):
            vals = [v for v in (m.get(rank), r.get(rank)) if v]
            m[rank] = min(vals) if vals else None
        m["volume"] = max(m.get("volume") or 0, r.get("volume") or 0)
        for k in ("relevancy", "cpc_exact", "cpc_broad", "sb_bid", "ease_of_ranking"):
            if m.get(k) is None and r.get(k) is not None:
                m[k] = r[k]
    return sorted(merged.values(), key=lambda k: k["volume"], reverse=True)


# --- sections ---------------------------------------------------------------------------------

def _asin_map(products: list[dict], discovered: int) -> dict:
    rows = []
    for p in products:
        rows.append({k: p.get(k) for k in ("asin", "parent_asin", "title", "price", "rating", "review_count",
                                            "monthly_sold", "sales_rank", "listed_since", "root_category")}
                    | {"est_monthly_revenue": round(p["monthly_sold"] * p["price"]) if p.get("monthly_sold") and p.get("price") else None})
    rows.sort(key=lambda r: (r["est_monthly_revenue"] or 0, -(r["sales_rank"] or 1e9)), reverse=True)
    return {
        "discovered": discovered,
        "fetched": len(products),
        "parents": len({p.get("parent_asin") or p["asin"] for p in products}),
        "categories": _counts(p.get("root_category") for p in products),
        "asins": rows,
    }


def _counts(values) -> dict:
    out: dict = defaultdict(int)
    for v in values:
        if v:
            out[v] += 1
    return dict(sorted(out.items(), key=lambda kv: kv[1], reverse=True))


def _quarter(day: str) -> str:
    d = dt.date.fromisoformat(day)
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def _catalogue(products: list[dict], js_sales: dict, top_asins: list[str]) -> dict:
    today = dt.date.today()
    cutoff = today.replace(year=today.year - 3).isoformat()
    launches = _counts(_quarter(p["listed_since"]) for p in products
                       if p.get("listed_since") and p["listed_since"] >= cutoff)
    launches = dict(sorted(launches.items()))
    last_12m = sum(v for q, v in launches.items() if q >= _quarter(today.replace(year=today.year - 1).isoformat()))

    revenue_monthly: dict[str, float] = defaultdict(float)
    for series in (js_sales or {}).values():
        for month, v in (series or {}).items():
            revenue_monthly[month] += v.get("revenue") or 0
    current_month = today.strftime("%Y-%m")
    revenue_monthly = {m: round(v) for m, v in sorted(revenue_monthly.items()) if m < current_month}

    yoy = None
    months = list(revenue_monthly)
    if len(months) >= 12:
        recent = sum(revenue_monthly[m] for m in months[-3:])
        year_ago = sum(revenue_monthly[m] for m in months[-12:-9])
        yoy = round((recent / year_ago - 1) * 100) if year_ago else None

    est = sorted((_revenue_proxy(p) if p.get("monthly_sold") else 0 for p in products), reverse=True)
    total_est = sum(est)

    bsr_trend = None
    tops = [p for p in products if p["asin"] in top_asins]
    if tops:
        def median_bsr(offset_months: int):
            month = (today.replace(day=1) - dt.timedelta(days=30 * offset_months)).strftime("%Y-%m")
            vals = [p["history"]["bsr_monthly"].get(month) for p in tops]
            vals = [v for v in vals if v]
            return statistics.median(vals) if vals else None
        now_bsr, then_bsr = median_bsr(1), median_bsr(13)
        if now_bsr and then_bsr:
            bsr_trend = {"median_bsr_now": now_bsr, "median_bsr_year_ago": then_bsr,
                         "improved": now_bsr < then_bsr, "change_pct": round((now_bsr / then_bsr - 1) * 100)}

    reviews_gained = 0
    for p in products:
        hist = p.get("history", {}).get("reviews_monthly") or {}
        if hist:
            months_sorted = sorted(hist)
            year_ago = [m for m in months_sorted if m <= (today.replace(year=today.year - 1)).strftime("%Y-%m")]
            base = hist[year_ago[-1]] if year_ago else 0
            reviews_gained += max(0, hist[months_sorted[-1]] - base)

    return {
        "asin_count": len(products),
        "launches_by_quarter": launches,
        "launches_last_12m": last_12m,
        "revenue_monthly_top_parents": revenue_monthly,
        "revenue_yoy_pct_last_3m": yoy,
        "est_monthly_revenue_keepa": round(total_est) if total_est else None,
        "top3_revenue_share": round(sum(est[:3]) / total_est, 2) if total_est else None,
        "bsr_trend_top_parents": bsr_trend,
        "reviews_gained_12m": int(reviews_gained),
    }


def _content(products: list[dict], top_asins: list[str], catalog_items: list[dict]) -> dict:
    by_asin = {p["asin"]: p for p in products}
    spapi = {i["asin"]: i for i in catalog_items or []}
    parents = []
    for asin in top_asins:
        p = dict(by_asin.get(asin) or {"asin": asin})
        if asin in spapi:  # SP-API image/bullet counts are authoritative when present
            for k in ("image_count", "bullet_count", "bullet_avg_len"):
                if spapi[asin].get(k):
                    p[k] = spapi[asin][k]
        result = check_listing(p)
        parents.append({"asin": asin, "title": p.get("title"), **result})

    def share(pred) -> float | None:
        return round(sum(1 for p in products if pred(p)) / len(products), 2) if products else None

    # Single-ASIN listings that look like they should be one variation family
    singles = [p for p in products if (p.get("parent_asin") or p["asin"]) == p["asin"] and not p.get("variation_count")]
    stems: dict[str, list[str]] = defaultdict(list)
    for p in singles:
        stem = " ".join(re.findall(r"[a-z0-9]+", (p.get("title") or "").lower())[:4])
        if stem:
            stems[stem].append(p["asin"])
    consolidation = [{"title_stem": s, "asins": a} for s, a in stems.items() if len(a) > 1]

    return {
        "summary": {
            "avg_score_top_parents": round(statistics.mean(p["score"] for p in parents)) if parents else None,
            "share_under_7_images": share(lambda p: (p.get("image_count") or 0) < 7),
            "share_no_video": share(lambda p: not p.get("video_count")),
            "share_no_aplus": share(lambda p: not p.get("has_aplus")),
            "share_under_5_bullets": share(lambda p: (p.get("bullet_count") or 0) < 5),
            "share_rating_below_4_2": share(lambda p: p.get("rating") is not None and p["rating"] < 4.2),
            "has_brand_store": any(p.get("brand_store") for p in products) if products else None,
        },
        "top_parents": parents,
        "variation_consolidation": consolidation,
    }


def _has_brand(text: str | None, brand: str) -> bool:
    """Spacing/case-insensitive: 'Superfacialist' matches brand 'Super Facialist'."""
    b = checks.norm(brand)
    return bool(b) and b in checks.norm(text)


def _is_ours(item: dict, our_asins: set[str], brand: str) -> bool:
    return item.get("asin") in our_asins or _has_brand(item.get("title"), brand)


def _guess_brand(title: str) -> str:
    words = (title or "").split()
    return " ".join(words[:2]) if words else "unknown"


def _competitors(sov: list[dict], serps: dict, brand: str, our_asins: set[str], prev_sov: list[dict] | None) -> dict:
    agg: dict[str, dict] = defaultdict(lambda: {"sov": 0.0, "sponsored_sov": 0.0, "keywords": 0})
    category_sov = [s for s in sov if not _has_brand(s["keyword"], brand)]
    for s in category_sov:
        for b in s["brands"]:
            a = agg[b["brand"] or "unknown"]
            a["sov"] += _frac(b["sov"])
            a["sponsored_sov"] += _frac(b["sponsored_sov"])
            a["keywords"] += 1
    n = len(category_sov) or 1
    table = sorted(({"brand": k, "avg_sov": round(v["sov"] / n, 3), "avg_sponsored_sov": round(v["sponsored_sov"] / n, 3),
                     "keywords_present": v["keywords"]} for k, v in agg.items()), key=lambda r: r["avg_sov"], reverse=True)
    for r in table:
        r["is_prospect"] = _has_brand(r["brand"], brand)

    sov_change = None
    if prev_sov:
        prev = _competitors(prev_sov, {}, brand, our_asins, None)["share_of_voice"]
        prev_map = {r["brand"]: r["avg_sov"] for r in prev}
        sov_change = [{"brand": r["brand"], "change": round(r["avg_sov"] - prev_map.get(r["brand"], 0), 3)}
                      for r in table[:15]]
        sov_change.sort(key=lambda r: r["change"], reverse=True)

    brand_attackers, ours_sponsored_on_brand = [], False
    positioning = {"our_prices": [], "our_ratings": [], "comp_prices": [], "comp_ratings": []}
    for s in (serps or {}).get("serps", []):
        is_brand_term = s["keyword"] in (serps.get("brand_terms") or [])
        for it in s["items"]:
            ours = _is_ours(it, our_asins, brand)
            if is_brand_term and it["sponsored"]:
                if ours:
                    ours_sponsored_on_brand = True
                else:
                    brand_attackers.append({"keyword": s["keyword"], "asin": it["asin"], "brand_guess": _guess_brand(it["title"]),
                                            "title": it["title"][:90], "position": it["position"]})
            if not is_brand_term and not it["sponsored"] and (it.get("position") or 99) <= 20:
                key = "our" if ours else "comp"
                if it.get("price"):
                    positioning[f"{key}_prices"].append(it["price"])
                if it.get("rating"):
                    positioning[f"{key}_ratings"].append(it["rating"])

    med = lambda xs: round(statistics.median(xs), 2) if xs else None  # noqa: E731
    return {
        "share_of_voice": table[:15],
        "sov_change_vs_last_run": sov_change,
        "brand_term_attackers": brand_attackers,
        "prospect_sponsored_on_own_brand": ours_sponsored_on_brand,
        "positioning_page1": {
            "our_median_price": med(positioning["our_prices"]), "competitor_median_price": med(positioning["comp_prices"]),
            "our_median_rating": med(positioning["our_ratings"]), "competitor_median_rating": med(positioning["comp_ratings"]),
        },
    }


def _frac(v) -> float:
    v = v or 0
    return v / 100 if v > 1 else v


def _tier(kw: dict, brand: str, competitor_names: set[str], relevancy_cut: float | None) -> str:
    k = kw["keyword"]
    if _has_brand(k, brand):
        return "brand"
    if any(c in k for c in competitor_names):
        return "competitor"
    if len(k.split()) >= 4 or (kw.get("volume") or 0) < 500:
        return "long_tail"
    rel = kw.get("relevancy")
    if (kw.get("organic_rank") or 999) <= PAGE_ONE or (rel is not None and relevancy_cut is not None and rel >= relevancy_cut):
        return "core"
    return "category"


def _status(kw: dict) -> str:
    org, spo = kw.get("organic_rank"), kw.get("sponsored_rank")
    if org and org <= TOP_OF_PAGE:
        return "own" if spo else "organic_top_unprotected"
    if org and org <= PAGE_TWO:
        return "sponsored_support" if spo else "push"
    if spo:
        return "sponsored_only"
    return "missing"


GAP_WEIGHT = {"push": 1.0, "missing": 0.6, "organic_top_unprotected": 0.5, "sponsored_only": 0.4,
              "sponsored_support": 0.3, "own": 0.1}


def _cpc(kw: dict, bids: dict, sov_by_kw: dict) -> float | None:
    if kw["keyword"] in bids:
        return bids[kw["keyword"]]["suggested"]
    for k in ("cpc_exact", "cpc_broad"):
        if kw.get(k):
            return kw[k]
    return (sov_by_kw.get(kw["keyword"]) or {}).get("suggested_bid_median")


def _strategy(keywords: list[dict], sov: list[dict], bids: dict, brand: str, competitor_names: set[str],
              attacked_brand_terms: set[str], products: list[dict]) -> dict:
    sov_by_kw = {s["keyword"]: s for s in sov}
    rels = sorted(k["relevancy"] for k in keywords if k.get("relevancy") is not None)
    relevancy_cut = rels[int(len(rels) * 0.75)] if rels else None

    kmap = []
    for kw in keywords:
        tier = _tier(kw, brand, competitor_names, relevancy_cut)
        status = _status(kw)
        if tier == "brand" and kw["keyword"] in attacked_brand_terms and status in {"organic_top_unprotected", "missing"}:
            status = "brand_defence_gap"
        cpc = _cpc(kw, bids, sov_by_kw)
        gap = 1.0 if status == "brand_defence_gap" else GAP_WEIGHT.get(status, 0.3)
        tier_weight = {"brand": 1.0, "core": 1.0, "category": 0.7, "long_tail": 0.5, "competitor": 0.3}[tier]
        priority = (kw.get("volume") or 0) * tier_weight * gap / max(cpc or 1.0, 0.2)
        kmap.append({"keyword": kw["keyword"], "tier": tier, "volume": kw.get("volume"), "organic_rank": kw.get("organic_rank"),
                     "sponsored_rank": kw.get("sponsored_rank"), "cpc": round(cpc, 2) if cpc else None,
                     "status": status, "priority": round(priority)})
    kmap.sort(key=lambda r: r["priority"], reverse=True)

    focus = [k for k in kmap if k["status"] in {"push", "missing", "brand_defence_gap", "organic_top_unprotected"}
             and k["tier"] != "competitor"][:20]

    by_tier: dict[str, float] = defaultdict(float)
    for k in focus:
        if k["cpc"] and k["volume"]:
            by_tier[k["tier"]] += k["volume"] * CLICKS_PER_SEARCH["mid"] * TARGET_SPONSORED_SOV[k["tier"]] * k["cpc"]
    by_ad_type: dict[str, float] = defaultdict(float)
    for tier, spend in by_tier.items():
        for ad_type, share in AD_TYPE_SPLIT[tier].items():
            by_ad_type[ad_type] += spend * share

    repeat = _repeat_signals(products)
    retention_share = 0.15 if repeat["likelihood"] == "high" else 0.10
    subtotal = sum(by_tier.values())
    if subtotal:
        by_ad_type["SD (remarketing/retention)"] = subtotal * retention_share / (1 - retention_share)

    tiers_summary = defaultdict(lambda: {"keywords": 0, "volume": 0, "gaps": 0})
    for k in kmap:
        t = tiers_summary[k["tier"]]
        t["keywords"] += 1
        t["volume"] += k["volume"] or 0
        t["gaps"] += k["status"] in {"push", "missing", "brand_defence_gap"}

    return {
        "keyword_map": kmap[:150],
        "tiers": dict(tiers_summary),
        "focus_keywords": focus,
        "budget": {
            "monthly_by_tier": {k: round(v) for k, v in by_tier.items()},
            "monthly_by_ad_type": {k: round(v) for k, v in by_ad_type.items()},
            "monthly_total": round(sum(by_ad_type.values())),
            "assumptions": {"clicks_per_search": CLICKS_PER_SEARCH["mid"], "target_sponsored_sov": TARGET_SPONSORED_SOV,
                            "ad_type_split": AD_TYPE_SPLIT, "retention_share": retention_share},
        },
        "repeat_signals": repeat,
    }


def _repeat_signals(products: list[dict]) -> dict:
    if not products:
        return {"likelihood": "unknown"}
    sns = sum(1 for p in products if p.get("is_sns")) / len(products)
    multipack = sum(1 for p in products if MULTIPACK.search(p.get("title") or "")) / len(products)
    cats = " ".join(" ".join(p.get("category_path") or []) for p in products[:30])
    consumable = bool(CONSUMABLE_CATEGORIES.search(cats))
    score = (sns > 0.2) + (multipack > 0.15) + consumable
    return {"sns_share": round(sns, 2), "multipack_share": round(multipack, 2), "consumable_category": consumable,
            "likelihood": ["low", "medium", "high", "high"][score]}


def _observed_ads(keywords: list[dict], sov: list[dict], brand: str, bids: dict) -> dict:
    """What we can see of their advertising from outside, plus a rough spend range."""
    top = keywords[:30]
    sponsored = [k for k in top if k.get("sponsored_rank")]
    sov_by_kw = {s["keyword"]: s for s in sov}
    low = high = 0.0
    for s in sov:
        mine = [b for b in s["brands"] if _has_brand(b["brand"], brand)]
        cpc = _cpc({"keyword": s["keyword"]}, bids, sov_by_kw)
        if mine and s.get("volume_30d") and cpc:
            share = _frac(mine[0]["sponsored_sov"])
            low += s["volume_30d"] * share * CLICKS_PER_SEARCH["low"] * cpc
            high += s["volume_30d"] * share * CLICKS_PER_SEARCH["high"] * cpc
    return {
        "top30_keywords_with_sponsored_rank": len(sponsored),
        "top30_keywords": len(top),
        "sponsored_coverage": round(len(sponsored) / len(top), 2) if top else None,
        "est_monthly_spend_on_sampled_terms": {"low": round(low), "high": round(high)} if high else None,
        "note": "Estimate from share of voice x search volume x assumed ad click rate x CPC benchmark on sampled terms only.",
    }


def _amc_benchmark(products: list[dict]) -> dict | None:
    cats = [p.get("root_category") for p in products if p.get("root_category")]
    if not cats:
        return None
    top_cat = max(set(cats), key=cats.count)
    slug = re.sub(r"[^a-z0-9]+", "-", top_cat.lower()).strip("-")
    path = ROOT / "benchmarks" / f"amc_{slug}.json"
    bench = read_json(path)
    return bench or {"category": top_cat, "available": False}


def _previous_sov(run: Path) -> list[dict] | None:
    prefix = run.name.rsplit("-", 3)[0]
    older = sorted(d for d in RUNS_DIR.glob(f"{prefix}-*") if d.is_dir() and d.name < run.name)
    for d in reversed(older):
        prev = read_json(d / "js_sov.json")
        if prev:
            return prev
    return None


def build(run: Path) -> dict:
    target = read_json(run / "input.json", {})
    mp = MARKETPLACES[target.get("marketplace", "us")]
    kp = read_json(run / "keepa_products.json", {"discovered": 0, "products": []})
    products = kp["products"]
    brand = target.get("brand") or ""
    catalog = read_json(run / "js_catalog.json") or catalog_from_keepa(products)
    our_asins = {p["asin"] for p in catalog} | {p["asin"] for p in products} | set(target.get("seed_asins") or [])
    js_sales = read_json(run / "js_sales.json", {})
    keywords = read_json(run / "keywords.json", [])
    per_asin_kw = read_json(run / "keywords_by_asin.json", {})
    sov = read_json(run / "js_sov.json", [])
    serps = read_json(run / "serps.json", {})
    bids = read_json(run / "ads_bids.json", {})

    focus = checks.select_heroes(catalog)
    run_dir_name = run
    top = [h["asin"] for h in focus["heroes"]] or list(js_sales) or top_parents(products, 10)

    competitors = _competitors(sov, serps, brand, our_asins, _previous_sov(run))
    competitor_names = {r["brand"].lower() for r in competitors["share_of_voice"]
                        if r["brand"] and not r["is_prospect"] and len(r["brand"]) >= 3}
    attacked = {a["keyword"] for a in competitors["brand_term_attackers"]}
    strategy = _strategy(keywords, sov, bids, brand, competitor_names, attacked, products)

    return {
        "prospect": {"brand": target.get("brand"), "marketplace": target.get("marketplace"), "domain": mp["domain"],
                     "currency": mp["currency"], "input": target.get("input"), "seller_name": target.get("seller_name"),
                     "landing_asin": (target.get("seed_asins") or [None])[0]},
        "generated": dt.date.today().isoformat(),
        "coverage": read_json(run / "collect_log.json", {}),
        "focus": {k: v for k, v in focus.items() if k != "heroes"},
        "heroes": _with_sheets(_heroes(focus["heroes"], catalog, products, per_asin_kw, brand, competitor_names,
                                      attacked, bids, sov), run_dir_name),
        "quick_wins": _quick_wins(catalog, brand),
        "asin_map": _asin_map(products, kp["discovered"]),
        "catalogue": _catalogue(products, js_sales, top),
        "content": _content(products, top, read_json(run / "catalog.json", [])),
        "ads_observed": _observed_ads(keywords, sov, brand, bids),
        "competitors": competitors,
        "strategy": strategy,
        "amc_benchmark": _amc_benchmark(products),
        "job_ad_present": (run / "job_ad.txt").exists(),
    }


def catalog_from_keepa(products: list[dict]) -> list[dict]:
    """Fallback catalogue when Jungle Scout isn't available: Keepa's 'bought in past month' as units."""
    return [{"asin": p["asin"], "parent_asin": p.get("parent_asin") or p["asin"], "title": p.get("title"),
             "brand": p.get("brand"), "category": p.get("root_category"), "price": p.get("price"),
             "units_30d": p.get("monthly_sold"), "revenue_30d": (p.get("monthly_sold") or 0) * (p.get("price") or 0),
             "sellers": p.get("offer_count"), "available": p.get("price") is not None,
             "rating": p.get("rating"), "reviews": p.get("review_count"), "source": "keepa"} for p in products]


def _heroes(heroes: list[dict], catalog: list[dict], products: list[dict], per_asin_kw: dict, brand: str,
            competitor_names: set[str], attacked: set[str], bids: dict, sov: list[dict]) -> list[dict]:
    by_asin = {p["asin"]: p for p in catalog}
    keepa_by_asin = {p["asin"]: p for p in products}
    fams = checks.families(catalog)
    sov_by_kw = {s["keyword"]: s for s in sov}
    out = []
    owners = [p.get("buy_box_owner") for p in catalog if checks.is_live(p) and p.get("buy_box_owner")]
    top_owner = max(set(owners), key=owners.count) if owners else None
    # One seller holding the Buy Box across nearly the whole range is the brand's own account.
    brand_seller = top_owner if owners and owners.count(top_owner) / len(owners) >= 0.8 else None
    for h in heroes:
        family_asins = [h["asin"], *h["children"]]
        h = {**h, "asin": _live_lead(h, keepa_by_asin)}
        js, kp = by_asin.get(h["asin"], {}), keepa_by_asin.get(h["asin"], {})
        p = {**js, **{k: v for k, v in kp.items() if v not in (None, [], "")}}
        p["price"] = js.get("price") or kp.get("price")
        p["rating"] = kp.get("rating") or js.get("rating")
        p["review_count"] = kp.get("review_count") or js.get("reviews")
        title = p.get("title") or ""
        leaf = (kp.get("category_path") or [None])[-1] or js.get("category")
        flags = []
        if mm := checks.category_mismatch(title, leaf):
            flags.append({"type": "wrong_category", "detail": f"{mm['product_type']} listed under {mm['category']}"})
        if mixed := checks.mixed_family(fams.get(h["parent_asin"], [])):
            flags.append({"type": "mixed_variation_family", "detail": "variation family mixes " + ", ".join(mixed)})
        flags += [{"type": "sellers", "detail": d} for d in checks.seller_flags(p, brand, brand_seller)]
        if s := checks.stock_flag(p):
            flags.append({"type": "stock", "detail": s})
        if s := checks.price_flag(p):
            flags.append({"type": "price", "detail": s})

        # keywords were pulled for one variant with include_variants, so they describe the family
        kws = merge_keywords([r for a in family_asins for r in per_asin_kw.get(a, [])])
        # judge relevance against every title in the family: variants often word the same product differently
        family_text = " ".join(filter(None, [title] + [by_asin.get(a, {}).get("title") for a in family_asins]
                                      + [keepa_by_asin.get(a, {}).get("title") for a in family_asins]))
        wasted = checks.wasted_terms(family_text, brand, kws)
        wasted_set = {w["keyword"] for w in wasted}
        targets = []
        title_stems = checks.stems(family_text) - checks.stems(brand)
        for kw in kws:
            # skip wasted terms, and terms that belong to a sibling in the family (e.g. "face oil" on a balm)
            if kw["keyword"] in wasted_set or not (checks.stems(kw["keyword"]) & title_stems):
                continue
            tier = _tier(kw, brand, competitor_names, None)
            status = _status(kw)
            if tier == "brand" and kw["keyword"] in attacked and status in {"organic_top_unprotected", "missing"}:
                status = "brand_defence_gap"
            if status in {"push", "brand_defence_gap", "organic_top_unprotected"} and tier != "competitor":
                cpc = _cpc(kw, bids, sov_by_kw)
                targets.append({"keyword": kw["keyword"], "tier": tier, "status": status, "volume": kw.get("volume"),
                                "organic_rank": kw.get("organic_rank"), "sponsored_rank": kw.get("sponsored_rank"),
                                "cpc": round(cpc, 2) if cpc else None})
        targets.sort(key=lambda t: t["volume"] or 0, reverse=True)
        out.append({
            "asin": h["asin"], "parent_asin": h["parent_asin"], "title": title,
            "family_revenue_30d": h["revenue_30d"], "family_size": len(h["children"]),
            "family_revenue_keepa": _keepa_revenue(family_asins, keepa_by_asin),
            "units_30d": p.get("units_30d") or p.get("monthly_sold"), "price": p.get("price"),
            "list_price": p.get("list_price"), "sellers": p.get("sellers") or p.get("offer_count"),
            "buy_box_owner": p.get("buy_box_owner"),
            "sold_by": "Amazon" if checks.sold_by_amazon(p) else p.get("buy_box_owner"), "category": leaf, "product_type": checks.product_type(title),
            "rating": p.get("rating"), "reviews": p.get("reviews") or p.get("review_count"),
            "content": check_listing(p) if kp else None,
            "mobile": mobile.check(p, brand) if kp else None,
            "flags": flags, "targets": targets[:6], "wasted_terms": wasted[:8],
            "sponsored_terms": sum(1 for k in kws if k.get("sponsored_rank")),
        })
    return out


def _with_sheets(heroes: list[dict], run: Path) -> list[dict]:
    """Point each best-seller at its phone-size image sheet, if the images step made one."""
    for h in heroes:
        sheet = run / "mobile" / f"{h['asin']}.png"
        h["mobile_sheet"] = str(sheet.relative_to(run)) if sheet.exists() else None
    return heroes


def _keepa_revenue(asins: list[str], keepa_by_asin: dict) -> int | None:
    """Cross-check from Keepa's 'bought in past month' (a lower bound) x current price, per variant."""
    total = sum((k.get("monthly_sold") or 0) * (k.get("price") or 0)
                for k in (keepa_by_asin.get(a) for a in dict.fromkeys(asins)) if k)
    return round(total) or None


def _live_lead(hero: dict, keepa_by_asin: dict) -> str:
    """Jungle Scout repeats family sales on every child, so it can't say which variant really sells.
    Prefer a child Keepa sees with a live offer: most bought last month, then best sales rank."""
    live = [keepa_by_asin[a] for a in hero["children"] if a in keepa_by_asin and keepa_by_asin[a].get("price")]
    if not live:
        return hero["asin"]
    return max(live, key=lambda k: (k.get("monthly_sold") or 0, -(k.get("sales_rank") or 1e9)))["asin"]


def _quick_wins(catalog: list[dict], brand: str) -> dict:
    live = [p for p in catalog if checks.is_live(p)]
    mixed = []
    for parent, kids in checks.families(live).items():
        if types := checks.mixed_family(kids):
            mixed.append({"parent_asin": parent, "product_types": types, "children": [k["asin"] for k in kids]})
    return {"duplicates": checks.duplicates(live, brand), "clutter": checks.clutter(live, brand),
            "mixed_families": mixed}
