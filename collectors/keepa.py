"""Keepa: ASIN discovery (brand / seller storefront) and per-ASIN listing + history data.

Docs: https://keepa.com/#!discuss/t/product-object/116  (csv indices, Keepa time)
"""
from __future__ import annotations

import datetime as dt
import json

from .common import MARKETPLACES, Budget, chunks, env, http_json

BASE = "https://api.keepa.com"
KEEPA_EPOCH_OFFSET_MIN = 21564000

# csv history indices
CSV_AMAZON, CSV_NEW, CSV_SALES_RANK, CSV_RATING, CSV_REVIEWS = 0, 1, 3, 16, 17


def keepa_time(minutes: int | None) -> dt.datetime | None:
    if not minutes or minutes <= 0:
        return None
    return dt.datetime.fromtimestamp((minutes + KEEPA_EPOCH_OFFSET_MIN) * 60, dt.UTC)


def _key() -> str:
    key = env("KEEPA_KEY")
    if not key:
        raise RuntimeError("KEEPA_KEY not set")
    return key


def _call(path: str, params: dict, budget: Budget, estimate: float):
    budget.spend("keepa", estimate)
    resp = http_json("GET", f"{BASE}/{path}", params={"key": _key(), **params})
    consumed = resp.get("tokensConsumed")
    if consumed is not None and consumed > estimate:
        budget.spend("keepa", consumed - estimate)
    return resp


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


def fetch_products(asins: list[str], marketplace: str, budget: Budget, history_days: int = 730) -> list[dict]:
    out = []
    for batch in chunks(asins, 100):
        resp = _call("product", {
            "domain": MARKETPLACES[marketplace]["keepa_domain"],
            "asin": ",".join(batch),
            "stats": 180,
            "rating": 1,
            "history": 1,
            "days": history_days,
            "videos": 1,
            "aplus": 1,
        }, budget, estimate=len(batch) * 2)
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
    stats_current = (p.get("stats") or {}).get("current") or []
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
        "rating": _last(rating),
        "review_count": int(_last(reviews)) if reviews else None,
        "image_count": _image_count(p),
        "video_count": len(p.get("videos") or []),
        "has_aplus": bool(p.get("aPlus")),
        "aplus_modules": len(p.get("aPlus") or []),
        "bullet_count": len(features),
        "bullet_avg_len": round(sum(len(f) for f in features) / len(features)) if features else 0,
        "title_len": len(p.get("title") or ""),
        "description_len": len(p.get("description") or ""),
        "variation_count": len(p.get("variations") or []),
        "variation_dimensions": sorted({a.get("dimension") for v in p.get("variations") or []
                                        for a in v.get("attributes") or [] if a.get("dimension")}),
        "is_sns": bool(p.get("isSNS")),
        "brand_store": p.get("brandStoreName") or p.get("brandStoreUrl"),
        "history": {
            "bsr_monthly": _monthly_last(bsr),
            "reviews_monthly": _monthly_last(reviews),
        },
        "source": "keepa",
    }
