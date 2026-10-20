"""Keepa: ASIN discovery (brand / seller storefront) and per-ASIN listing + history data.

Docs: https://keepa.com/#!discuss/t/product-object/116  (csv indices, Keepa time)
"""
from __future__ import annotations

import datetime as dt
import json
import math
import time

from .common import MARKETPLACES, Budget, env, http_json

BASE = "https://api.keepa.com"
KEEPA_EPOCH_OFFSET_MIN = 21564000

# csv history indices
CSV_AMAZON, CSV_NEW, CSV_SALES_RANK, CSV_LIST_PRICE, CSV_COUNT_NEW, CSV_RATING, CSV_REVIEWS = 0, 1, 3, 4, 11, 16, 17
TOKENS_PER_PRODUCT = 2  # base product + rating data

# Token pacing. Keepa refills at a fixed rate per minute (1/min on the smallest plan), so instead of
# failing when the bucket is empty we wait for it. Clock functions are swappable for tests.
_sleep, _now = time.sleep, time.time
_state: dict = {"left": None, "rate": None, "refill_in_ms": None, "waited_s": 0.0}
MAX_WAIT_S = float(env("APA_KEEPA_MAX_WAIT_MIN") or 45) * 60


def keepa_time(minutes: int | None) -> dt.datetime | None:
    if not minutes or minutes <= 0:
        return None
    return dt.datetime.fromtimestamp((minutes + KEEPA_EPOCH_OFFSET_MIN) * 60, dt.UTC)


def _key() -> str:
    key = env("KEEPA_KEY")
    if not key:
        raise RuntimeError("KEEPA_KEY not set")
    return key


def _remember(resp: dict) -> None:
    for src, dst in (("tokensLeft", "left"), ("refillRate", "rate"), ("refillIn", "refill_in_ms")):
        if resp.get(src) is not None:
            _state[dst] = resp[src]


def token_status() -> dict:
    """Free call: current balance and refill rate."""
    _remember(http_json("GET", f"{BASE}/token", params={"key": _key()}, cache=False))
    return dict(_state)


def _wait_for(tokens: float) -> None:
    left, rate = _state["left"], _state["rate"] or 1
    if left is None or left >= tokens:
        return
    refills = math.ceil((tokens - left) / rate)
    wait = (_state["refill_in_ms"] or 60_000) / 1000 + max(0, refills - 1) * 60 + 1
    if _state["waited_s"] + wait > MAX_WAIT_S:
        raise RuntimeError(f"Keepa needs {tokens - left:.0f} more tokens; waiting would exceed "
                           f"{MAX_WAIT_S / 60:.0f} min (APA_KEEPA_MAX_WAIT_MIN)")
    print(f"    … waiting {wait / 60:.1f} min for Keepa tokens ({left}/{tokens:.0f})", flush=True)
    _sleep(wait)
    _state["waited_s"] += wait
    _state["left"] = left + refills * rate


def _call(path: str, params: dict, budget: Budget, estimate: float):
    budget.spend("keepa", estimate)
    for _ in range(5):
        _wait_for(estimate)
        try:
            resp = http_json("GET", f"{BASE}/{path}", params={"key": _key(), **params}, retries=1)
        except RuntimeError as e:
            if "-> 429" not in str(e):
                raise
            _state["left"] = min(_state["left"] or 0, 0)  # bucket empty; wait a refill and retry
            continue
        _remember(resp)
        consumed = resp.get("tokensConsumed")
        if consumed is not None and consumed > estimate:
            budget.spend("keepa", consumed - estimate)
        return resp
    raise RuntimeError("Keepa kept returning 429 (out of tokens)")


def waited_minutes() -> float:
    return round(_state["waited_s"] / 60, 1)


def discover_by_brand(brand: str, marketplace: str, budget: Budget, per_page: int = 500) -> list[str]:
    selection = {"brand": [brand], "perPage": per_page, "page": 0,
                 "sort": [["current_SALES", "asc"]]}
    resp = _call("query", {"domain": MARKETPLACES[marketplace]["keepa_domain"],
                           "selection": json.dumps(selection)}, budget, estimate=10 + per_page / 100)
    return resp.get("asinList") or []


def discover_by_seller(seller_id: str, marketplace: str, budget: Budget) -> dict:
    resp = _call("seller", {"domain": MARKETPLACES[marketplace]["keepa_domain"],
                            "seller": seller_id, "storefront": 1}, budget, estimate=10)
    seller = (resp.get("sellers") or {}).get(seller_id) or {}
    return {"seller_name": seller.get("sellerName"), "asins": seller.get("asinList") or []}


def fetch_products(asins: list[str], marketplace: str, budget: Budget, history_days: int = 400) -> list[dict]:
    """Batches sized to the tokens on hand, so a small plan trickles through instead of failing."""
    out, todo = [], list(asins)
    while todo:
        affordable = int((_state["left"] or 0) // TOKENS_PER_PRODUCT) if _state["left"] is not None else 100
        batch, todo = todo[:max(1, min(100, affordable))], todo[max(1, min(100, affordable)):]
        resp = _call("product", {
            "domain": MARKETPLACES[marketplace]["keepa_domain"],
            "asin": ",".join(batch),
            "stats": 180,
            "rating": 1,
            "history": 1,
            "days": history_days,
            "videos": 1,
            "aplus": 1,
        }, budget, estimate=len(batch) * TOKENS_PER_PRODUCT)
        out.extend(parse_product(p) for p in resp.get("products") or [])
    return out


def _series(csv: list | None, idx: int, scale: float = 1.0) -> list[tuple[str, float]]:
    """Keepa csv arrays are flat [time, value, time, value...]; -1 means no data."""
    if not csv or idx >= len(csv) or not csv[idx]:
        return []
    raw = csv[idx]
    points = []
    for t, v in zip(raw[0::2], raw[1::2]):
        if v is None or v < 0:
            continue
        points.append((keepa_time(t).date().isoformat(), v * scale))
    return points


def _monthly_last(points: list[tuple[str, float]]) -> dict[str, float]:
    by_month: dict[str, float] = {}
    for day, value in points:
        by_month[day[:7]] = value
    return by_month


def _last(points):
    return points[-1][1] if points else None


def _image_count(p: dict) -> int:
    if isinstance(p.get("images"), list):
        return len(p["images"])
    csv = p.get("imagesCSV")
    return len(csv.split(",")) if csv else 0


def parse_product(p: dict) -> dict:
    csv = p.get("csv") or []
    stats = p.get("stats") or {}
    stats_current = stats.get("current") or []
    oos90 = stats.get("outOfStockPercentage90") or []
    price_cents = None
    for idx in (CSV_AMAZON, CSV_NEW):
        if len(stats_current) > idx and stats_current[idx] and stats_current[idx] > 0:
            price_cents = stats_current[idx]
            break
    bsr = _series(csv, CSV_SALES_RANK)
    reviews = _series(csv, CSV_REVIEWS)
    rating = _series(csv, CSV_RATING, 0.1)
    listed = keepa_time(p.get("listedSince")) or keepa_time(p.get("trackingSince"))
    features = p.get("features") or []
    category_tree = [c.get("name") for c in p.get("categoryTree") or [] if c.get("name")]

    return {
        "asin": p.get("asin"),
        "parent_asin": p.get("parentAsin") or p.get("asin"),
        "title": p.get("title") or "",
        "brand": p.get("brand"),
        "manufacturer": p.get("manufacturer"),
        "category_path": category_tree,
        "root_category": category_tree[0] if category_tree else None,
        "listed_since": listed.date().isoformat() if listed else None,
        "price": price_cents / 100 if price_cents else None,
        "monthly_sold": p.get("monthlySold"),
        "sales_rank": _last(bsr),
        "rating": round(_last(rating), 1) if rating else None,
        "review_count": int(_last(reviews)) if reviews else None,
        "image_count": _image_count(p),
        "video_count": len(p.get("videos") or []),
        "has_aplus": bool(p.get("aPlus")),
        "aplus_modules": len(p.get("aPlus") or []),
        "bullet_count": len(features) if p.get("features") is not None else None,
        "bullet_avg_len": round(sum(len(f) for f in features) / len(features)) if features else None,
        "title_len": len(p.get("title") or ""),
        "description_len": len(p.get("description") or ""),
        "variation_count": len(p.get("variations") or []),
        "variation_dimensions": sorted({a.get("dimension") for v in p.get("variations") or []
                                        for a in v.get("attributes") or [] if a.get("dimension")}),
        "is_sns": bool(p.get("isSNS")),
        "list_price": stats_current[CSV_LIST_PRICE] / 100 if len(stats_current) > CSV_LIST_PRICE and (stats_current[CSV_LIST_PRICE] or 0) > 0 else None,
        "offer_count": stats_current[CSV_COUNT_NEW] if len(stats_current) > CSV_COUNT_NEW and (stats_current[CSV_COUNT_NEW] or -1) >= 0 else None,
        # index 1 = all new offers; index 0 (Amazon itself) is meaningless for brands selling 3P
        "oos_pct_90": next((v for v in (oos90[1:2] + oos90[:1]) if v is not None and v >= 0), None),
        "avg_price_90": (stats.get("avg90") or [None, None])[1] / 100 if len(stats.get("avg90") or []) > 1 and (stats["avg90"][1] or 0) > 0 else None,
        "brand_store": p.get("brandStoreName") or p.get("brandStoreUrl"),
        "history": {
            "bsr_monthly": _monthly_last(bsr),
            "reviews_monthly": _monthly_last(reviews),
        },
        "source": "keepa",
    }
