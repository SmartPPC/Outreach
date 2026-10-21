"""Turn whatever was pasted (ASIN, product URL, brand store URL, seller URL, brand name) into a target."""
from __future__ import annotations

import re
import urllib.parse

ASIN_RE = re.compile(r"\b(B0[A-Z0-9]{8}|\d{9}[\dX])\b")
URL_ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d|product-reviews)/([A-Z0-9]{10})", re.I)
STORE_RE = re.compile(r"/stores/(?:([^/]+)/)?page/([0-9A-F-]{36})", re.I)


def marketplace_from_host(host: str) -> str | None:
    host = host.lower()
    if host.endswith("amazon.co.uk"):
        return "uk"
    if host.endswith("amazon.com"):
        return "us"
    return None


def resolve(raw: str, marketplace: str | None = None) -> dict:
    raw = raw.strip()
    target = {
        "input": raw,
        "brand": None,
        "seller_id": None,
        "store_page_id": None,
        "seed_asins": [],
        "marketplace": marketplace,
    }

    if raw.startswith("http") or "amazon." in raw:
        url = raw if raw.startswith("http") else f"https://{raw}"
        parts = urllib.parse.urlsplit(url)
        target["marketplace"] = marketplace or marketplace_from_host(parts.netloc)
        query = dict(urllib.parse.parse_qsl(parts.query))

        if m := URL_ASIN_RE.search(parts.path):
            target["seed_asins"].append(m.group(1).upper())
        if query.get("lp_asin"):  # brand store links carry the product the shopper came from
            target["seed_asins"].append(query["lp_asin"].upper())
        if m := STORE_RE.search(parts.path):
            if m.group(1):
                slug = urllib.parse.unquote_plus(m.group(1)).replace("-", " ")
                # SuperFacialist -> Super Facialist, but keep UltraDEX / iPhone-style capitals together
                target["brand"] = re.sub(r"(?<=[a-z])(?=[A-Z][a-z])", " ", slug)
                target["brand_slug"] = slug
            target["store_page_id"] = m.group(2)
        for key in ("seller", "me"):
            if query.get(key):
                target["seller_id"] = query[key]
        # Search results filtered to a brand: /s?rh=p_89:Brand or /s?k=brand
        rh = query.get("rh", "")
        if m := re.search(r"p_(?:89|123):([^,]+)", rh):
            target["brand"] = urllib.parse.unquote_plus(m.group(1))
        if not target["brand"] and query.get("field-brandtextbin"):
            target["brand"] = query["field-brandtextbin"]
    else:
        asins = ASIN_RE.findall(raw.upper())
        if asins and len(" ".join(asins)) >= len(raw.replace(",", " ").strip()) - 2:
            target["seed_asins"] = list(dict.fromkeys(asins))
        else:
            target["brand"] = raw

    target["marketplace"] = target["marketplace"] or "us"
    # One product with no store, seller or brand context: audit that product, not the whole brand
    target["scope"] = "asin" if (len(target["seed_asins"]) == 1 and not target["brand"]
                                  and not target["seller_id"] and not target["store_page_id"]) else "brand"
    return target


def brand_spellings(*names: str | None) -> list[str]:
    """Every likely way a brand is written: as given, without spaces, and split at each case change.
    'UltraDEX' -> ['UltraDEX', 'Ultra DEX']; 'Super Facialist' -> ['Super Facialist', 'SuperFacialist']."""
    out: list[str] = []
    for name in filter(None, names):
        joined = name.replace(" ", "")
        for v in (name, joined, re.sub(r"(?<=[a-z])(?=[A-Z])", " ", joined),
                  re.sub(r"(?<=[a-z])(?=[A-Z][a-z])", " ", joined)):
            if v and v.lower() not in {o.lower() for o in out}:
                out.append(v)
    return out


def slug_for(target: dict, date: str) -> str:
    base = target.get("brand") or (target["seed_asins"][0] if target["seed_asins"] else target.get("seller_id") or "prospect")
    if target.get("scope") == "asin" and target["seed_asins"]:
        base = f"{base}-{target['seed_asins'][0]}"  # keep single-product audits apart from brand audits
    base = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    return f"{base}-{target['marketplace']}-{date}"


if __name__ == "__main__":
    import json
    import sys

    print(json.dumps(resolve(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None), indent=2))
