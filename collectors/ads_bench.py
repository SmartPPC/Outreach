"""Amazon Ads API: keyword bid recommendations as a CPC benchmark.

The Ads API only works for profiles you manage, so we ask for recommendations against a *proxy*
ASIN from one of your own accounts in a similar category (ADS_BENCH_ASIN_<MP>). Treat the output as
a market CPC benchmark, never as the prospect's bids.
Docs: https://advertising.amazon.com/API/docs/en-us/sponsored-products/3-0/openapi/prod#tag/Bid-Recommendations
"""
from __future__ import annotations

from .common import MARKETPLACES, Budget, chunks, env, http_json, lwa_access_token

_token_cache: dict[str, str] = {}


def configured(marketplace: str) -> bool:
    mp = marketplace.upper()
    return all(env(k) for k in ("ADS_CLIENT_ID", "ADS_CLIENT_SECRET", "ADS_REFRESH_TOKEN",
                                f"ADS_PROFILE_ID_{mp}", f"ADS_BENCH_ASIN_{mp}"))


def _headers(marketplace: str) -> dict:
    mp = MARKETPLACES[marketplace]
    if marketplace not in _token_cache:
        _token_cache[marketplace] = lwa_access_token(env("ADS_REFRESH_TOKEN"), env("ADS_CLIENT_ID"),
                                                     env("ADS_CLIENT_SECRET"), mp["ads_token_host"])
    return {
        "Authorization": f"Bearer {_token_cache[marketplace]}",
        "Amazon-Advertising-API-ClientId": env("ADS_CLIENT_ID"),
        "Amazon-Advertising-API-Scope": env(f"ADS_PROFILE_ID_{marketplace.upper()}"),
        "Content-Type": "application/vnd.spthemebasedbidrecommendation.v4+json",
        "Accept": "application/vnd.spthemebasedbidrecommendation.v4+json",
    }


def bid_recommendations(keywords: list[str], marketplace: str, budget: Budget) -> dict[str, dict]:
    """{keyword: {"low": x, "suggested": y, "high": z}} for exact match."""
    out: dict[str, dict] = {}
    proxy_asin = env(f"ADS_BENCH_ASIN_{marketplace.upper()}")
    for batch in chunks(keywords, 100):
        budget.spend("ads")
        resp = http_json("POST", f"{MARKETPLACES[marketplace]['ads_host']}/sp/targets/bid/recommendations",
                         headers=_headers(marketplace), body={
                             "recommendationType": "BIDS_FOR_NEW_AD_GROUP",
                             "asins": [proxy_asin],
                             "targetingExpressions": [{"type": "KEYWORD_EXACT_MATCH", "value": k} for k in batch],
                             "bidding": {"strategy": "LEGACY_FOR_SALES", "adjustments": None},
                         })
        out.update(parse_bids(resp))
    return out


def parse_bids(resp: dict) -> dict[str, dict]:
    out = {}
    for theme in resp.get("bidRecommendations") or []:
        for rec in theme.get("bidRecommendationsForTargetingExpressions") or []:
            expr = rec.get("targetingExpression") or {}
            values = sorted(v.get("suggestedBid") for v in rec.get("bidValues") or [] if v.get("suggestedBid"))
            if expr.get("value") and values:
                out[expr["value"]] = {"low": values[0], "suggested": values[len(values) // 2], "high": values[-1]}
    return out
