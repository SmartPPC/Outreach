"""DataForSEO: live Amazon SERPs (who is sponsored / ranking) and ranked keywords per ASIN.

Docs: https://docs.dataforseo.com/v3/merchant/amazon/products/  and  /v3/dataforseo_labs/amazon/ranked_keywords/
"""
from __future__ import annotations

import base64
import time

from .common import MARKETPLACES, Budget, env, http_json, proxy_auth

BASE = "https://api.dataforseo.com/v3"
TASK_READY, TASK_PENDING = 20000, {40601, 40602}


def configured() -> bool:
    return bool(env("DATAFORSEO_LOGIN") and env("DATAFORSEO_PASSWORD")) or proxy_auth("dataforseo")


def _headers() -> dict:
    if not env("DATAFORSEO_LOGIN"):
        return {}
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


def page_text(url: str, budget: Budget) -> dict | None:
    """Fetch and parse any web page through DataForSEO (our network can't reach brand sites directly).
    Returns {"url", "text", "links"} or None when the page doesn't exist."""
    budget.spend("dataforseo", 0.1)  # ~$0.00015 a page; counted as a tenth of a search task
    resp = http_json("POST", f"{BASE}/on_page/content_parsing/live", headers=_headers(), body=[{"url": url}])
    return parse_page(url, resp)


def parse_page(url: str, resp: dict) -> dict | None:
    task = (resp.get("tasks") or [{}])[0]
    item = ((task.get("result") or [{}])[0].get("items") or [None])[0]
    if not item or (item.get("status_code") or 0) >= 400:
        return None
    texts, links = [], []

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("text"), str):
                texts.append(node["text"])
            for u in node.get("urls") or []:
                if isinstance(u, dict) and u.get("url"):
                    links.append({"url": u["url"], "text": u.get("anchor_text") or ""})
            for v in node.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(item.get("page_content") or {})
    return {"url": url, "text": "\n".join(texts), "links": links}


def google(query: str, marketplace: str, budget: Budget, depth: int = 20) -> list[dict]:
    """Google results for a query (about $0.01 each): [{"title", "url", "description"}]."""
    mp = MARKETPLACES[marketplace]
    budget.spend("dataforseo")
    resp = http_json("POST", f"{BASE}/serp/google/organic/live/regular", headers=_headers(), body=[{
        "keyword": query, "location_code": mp["d4s_location"], "language_code": "en", "depth": depth}])
    task = (resp.get("tasks") or [{}])[0]
    items = ((task.get("result") or [{}])[0] or {}).get("items") or []
    return [{"title": i.get("title") or "", "url": i.get("url") or "", "description": i.get("description") or ""}
            for i in items if i.get("type") == "organic"]
