"""Jungle Scout API: sales estimates, keywords by ASIN (incl. organic/sponsored rank + PPC bids), share of voice.

Docs: https://developer.junglescout.com/api
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .common import MARKETPLACES, Budget, chunks, env, http_json, proxy_auth

BASE = "https://developer.junglescout.com/api"


def configured() -> bool:
    return bool(env("JS_KEY") and env("JS_KEY_NAME")) or proxy_auth("junglescout")


def _headers() -> dict:
    headers = {
        "X_API_Type": "junglescout",
        "Accept": "application/vnd.junglescout.v1+json",
        "Content-Type": "application/vnd.api+json",
    }
    if env("JS_KEY") and env("JS_KEY_NAME"):
        headers["Authorization"] = f"{env('JS_KEY_NAME')}:{env('JS_KEY')}"
    return headers


def sales_estimates(asin: str, marketplace: str, budget: Budget, months: int = 12) -> dict:
    """Daily unit estimates rolled up to months: {month: {"units": n, "revenue": r}}."""
    budget.spend("junglescout")
    end = dt.date.today() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=30 * months)
    resp = http_json("GET", f"{BASE}/sales_estimates_query", headers=_headers(), params={
        "marketplace": MARKETPLACES[marketplace]["js"], "asin": asin,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
    })
    return parse_sales(resp)


def parse_sales(resp: dict) -> dict:
    monthly: dict[str, dict] = defaultdict(lambda: {"units": 0.0, "revenue": 0.0})
    for row in resp.get("data") or []:
        for day in (row.get("attributes") or {}).get("data") or []:
            units = day.get("estimated_units_sold") or 0
            price = day.get("last_known_price") or 0
            m = monthly[day["date"][:7]]
            m["units"] += units
            m["revenue"] += units * price
    return {k: {"units": round(v["units"]), "revenue": round(v["revenue"], 2)} for k, v in sorted(monthly.items())}


def keywords_by_asin(asins: list[str], marketplace: str, budget: Budget, per_page: int = 100,
                     min_volume: int = 100) -> list[dict]:
    out = []
    for batch in chunks(asins, 10):
        budget.spend("junglescout")
        resp = http_json("POST", f"{BASE}/keywords/keywords_by_asin_query", headers=_headers(), params={
            "marketplace": MARKETPLACES[marketplace]["js"], "page[size]": per_page,
            "sort": "-monthly_search_volume_exact",
        }, body={"data": {"type": "keywords_by_asin_query", "attributes": {
            "asins": batch, "include_variants": True, "min_monthly_search_volume_exact": min_volume,
        }}})
        out.extend(parse_keywords(resp))
    return out


def parse_keywords(resp: dict) -> list[dict]:
    rows = []
    for item in resp.get("data") or []:
        a = item.get("attributes") or {}
        rows.append({
            "keyword": a.get("name") or item.get("id", "").split("/", 1)[-1],
            "volume": a.get("monthly_search_volume_exact") or 0,
            "volume_broad": a.get("monthly_search_volume_broad") or 0,
            "organic_rank": a.get("organic_rank"),
            "sponsored_rank": a.get("sponsored_rank"),
            "relevancy": a.get("relevancy_score"),
            "ease_of_ranking": a.get("ease_of_ranking_score"),
            "cpc_exact": a.get("ppc_bid_exact"),
            "cpc_broad": a.get("ppc_bid_broad"),
            "sb_bid": a.get("sp_brand_ad_bid"),
            "sponsored_product_count": a.get("sponsored_product_count"),
            "competitor_ranks": a.get("competitor_organic_rank") or [],
            "source": "junglescout",
        })
    return rows


def share_of_voice(keyword: str, marketplace: str, budget: Budget) -> dict:
    budget.spend("junglescout")
    resp = http_json("GET", f"{BASE}/share_of_voice", headers=_headers(), params={
        "marketplace": MARKETPLACES[marketplace]["js"], "keyword": keyword,
    })
    return parse_sov(keyword, resp)


def parse_sov(keyword: str, resp: dict) -> dict:
    a = (resp.get("data") or {}).get("attributes") or {}
    brands = [{
        "brand": b.get("brand"),
        "sov": b.get("combined_weighted_sov") or 0,
        "organic_sov": b.get("organic_weighted_sov") or 0,
        "sponsored_sov": b.get("sponsored_weighted_sov") or 0,
        "sponsored_products": b.get("sponsored_products") or 0,
        "avg_price": b.get("combined_average_price"),
    } for b in a.get("brands") or []]
    brands.sort(key=lambda b: b["sov"], reverse=True)
    return {
        "keyword": keyword,
        "volume_30d": a.get("estimated_30_day_search_volume"),
        "suggested_bid_median": a.get("exact_suggested_bid_median"),
        "brands": brands,
    }
