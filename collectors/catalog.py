"""SP-API Catalog Items 2022-04-01: brand search + authoritative listing attributes for any ASIN.

Works for ASINs you don't sell: catalog data is public within the marketplace.
Docs: https://developer-docs.amazon.com/sp-api/docs/catalog-items-api-v2022-04-01-reference
"""
from __future__ import annotations

from .common import MARKETPLACES, Budget, env, http_json, lwa_access_token

VERSION = "2022-04-01"
_token_cache: dict[str, str] = {}


def configured() -> bool:
    return all(env(k) for k in ("SPAPI_CLIENT_ID", "SPAPI_CLIENT_SECRET", "SPAPI_REFRESH_TOKEN"))


def _headers() -> dict:
    if "token" not in _token_cache:
        _token_cache["token"] = lwa_access_token(env("SPAPI_REFRESH_TOKEN"), env("SPAPI_CLIENT_ID"),
                                                 env("SPAPI_CLIENT_SECRET"))
    return {"x-amz-access-token": _token_cache["token"]}


def search_brand(brand: str, marketplace: str, budget: Budget, max_pages: int = 5) -> list[str]:
    mp = MARKETPLACES[marketplace]
    asins, page_token = [], None
    for _ in range(max_pages):
        budget.spend("spapi")
        params = {"marketplaceIds": mp["marketplace_id"], "keywords": brand, "brandNames": brand,
                  "includedData": "summaries", "pageSize": 20}
        if page_token:
            params["pageToken"] = page_token
        resp = http_json("GET", f"{mp['spapi_host']}/catalog/{VERSION}/items", headers=_headers(), params=params)
        asins += [i["asin"] for i in resp.get("items") or []]
        page_token = (resp.get("pagination") or {}).get("nextToken")
        if not page_token:
            break
    return list(dict.fromkeys(asins))


def get_items(asins: list[str], marketplace: str, budget: Budget) -> list[dict]:
    mp = MARKETPLACES[marketplace]
    out = []
    for asin in asins:
        budget.spend("spapi")
        resp = http_json("GET", f"{mp['spapi_host']}/catalog/{VERSION}/items/{asin}", headers=_headers(), params={
            "marketplaceIds": mp["marketplace_id"],
            "includedData": "attributes,images,relationships,summaries",
        })
        out.append(parse_item(resp))
    return out


def parse_item(item: dict) -> dict:
    attrs = item.get("attributes") or {}
    summary = (item.get("summaries") or [{}])[0]
    images = [img for group in item.get("images") or [] for img in group.get("images") or []]
    variants = {img.get("variant") for img in images}
    bullets = [b.get("value", "") for b in attrs.get("bullet_point") or []]
    parents, children = [], []
    for group in item.get("relationships") or []:
        for rel in group.get("relationships") or []:
            parents += rel.get("parentAsins") or []
            children += rel.get("childAsins") or []
    return {
        "asin": item.get("asin"),
        "title": summary.get("itemName"),
        "brand": summary.get("brand") or summary.get("brandName"),
        "image_count": len(variants - {None}),
        "bullet_count": len(bullets),
        "bullet_avg_len": round(sum(map(len, bullets)) / len(bullets)) if bullets else 0,
        "parent_asins": parents,
        "child_asins": children,
        "source": "spapi",
    }
