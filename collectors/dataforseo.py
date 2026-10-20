"""DataForSEO: live Amazon SERPs (who is sponsored / ranking) and ranked keywords per ASIN.

Docs: https://docs.dataforseo.com/v3/merchant/amazon/products/  and  /v3/dataforseo_labs/amazon/ranked_keywords/
"""
from __future__ import annotations

import base64
import time

from .common import MARKETPLACES, Budget, env, http_json

BASE = "https://api.dataforseo.com/v3"
TASK_READY, TASK_PENDING = 20000, {40601, 40602}


def configured() -> bool:
    return bool(env("DATAFORSEO_LOGIN") and env("DATAFORSEO_PASSWORD"))


def _headers() -> dict:
    token = base64.b64encode(f"{env('DATAFORSEO_LOGIN')}:{env('DATAFORSEO_PASSWORD')}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def serp(keyword: str, marketplace: str, budget: Budget, depth: int = 48, timeout_s: int = 300) -> dict:
    """Amazon search results page for a keyword. Async task API: post, then poll."""
    mp = MARKETPLACES[marketplace]
    budget.spend("dataforseo")
    posted = http_json("POST", f"{BASE}/merchant/amazon/products/task_post", headers=_headers(), body=[{
        "keyword": keyword, "location_code": mp["d4s_location"], "language_code": mp["d4s_language"],
        "depth": depth, "priority": 2,
    }])
    task_id = posted["tasks"][0]["id"]
    deadline = time.time() + timeout_s
    while True:
        resp = http_json("GET", f"{BASE}/merchant/amazon/products/task_get/advanced/{task_id}",
                         headers=_headers(), cache=False)
        task = resp["tasks"][0]
        if task.get("status_code") == TASK_READY:
            return parse_serp(keyword, resp)
        if task.get("status_code") not in TASK_PENDING or time.time() > deadline:
            raise RuntimeError(f"DataForSEO task {task_id}: {task.get('status_code')} {task.get('status_message')}")
        time.sleep(10)


def parse_serp(keyword: str, resp: dict) -> dict:
    result = ((resp.get("tasks") or [{}])[0].get("result") or [{}])[0]
    items = []
    for it in result.get("items") or []:
        kind = it.get("type", "")
        items.append({
            "asin": it.get("data_asin"),
            "title": it.get("title") or "",
            "position": it.get("rank_absolute"),
            "sponsored": "paid" in kind,
            "type": kind,
            "price": it.get("price_from"),
            "rating": (it.get("rating") or {}).get("value"),
            "reviews": (it.get("rating") or {}).get("votes_count"),
            "is_best_seller": it.get("is_best_seller"),
            "is_amazon_choice": it.get("is_amazon_choice"),
        })
    return {"keyword": keyword, "total_results": result.get("se_results_count"), "items": items}


def ranked_keywords(asin: str, marketplace: str, budget: Budget, limit: int = 200) -> list[dict]:
    """Fallback keyword source when Jungle Scout isn't available."""
    mp = MARKETPLACES[marketplace]
    budget.spend("dataforseo")
    resp = http_json("POST", f"{BASE}/dataforseo_labs/amazon/ranked_keywords/live", headers=_headers(), body=[{
        "asin": asin, "location_code": mp["d4s_location"], "language_code": mp["d4s_language"], "limit": limit,
    }])
    return parse_ranked(resp)


def parse_ranked(resp: dict) -> list[dict]:
    result = ((resp.get("tasks") or [{}])[0].get("result") or [{}])[0]
    rows = []
    for it in result.get("items") or []:
        kd = it.get("keyword_data") or {}
        serp_item = (it.get("ranked_serp_element") or {}).get("serp_item") or {}
        paid = "paid" in (serp_item.get("type") or "")
        rows.append({
            "keyword": kd.get("keyword"),
            "volume": (kd.get("keyword_info") or {}).get("search_volume") or 0,
            "organic_rank": None if paid else serp_item.get("rank_absolute"),
            "sponsored_rank": serp_item.get("rank_absolute") if paid else None,
            "relevancy": None,
            "cpc_exact": None,
            "source": "dataforseo",
        })
    return rows
