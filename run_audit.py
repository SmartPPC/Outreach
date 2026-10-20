"""Collect everything for one prospect, then build dataset.json.

    python run_audit.py "https://www.amazon.co.uk/stores/Acme/page/..." [--job-ad job.txt]

Any provider without credentials is skipped and noted in collect_log.json, so a partial setup still
produces a (thinner) audit. Re-running the same prospect hits the on-disk cache, not the APIs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
import traceback
from pathlib import Path

from analyse import build_dataset
from collectors import ads_bench, catalog, dataforseo, junglescout, keepa
from collectors.common import Budget, BudgetExceeded, env, load_env, run_dir, write_json
from collectors.resolve import resolve, slug_for


class Log:
    def __init__(self):
        self.steps: list[dict] = []

    def ok(self, step: str, **info):
        self.steps.append({"step": step, "status": "ok", **info})
        print(f"  ✓ {step} {info or ''}")

    def skip(self, step: str, reason: str):
        self.steps.append({"step": step, "status": "skipped", "reason": reason})
        print(f"  – {step}: skipped ({reason})")

    def fail(self, step: str, err: Exception):
        self.steps.append({"step": step, "status": "failed", "error": str(err)})
        print(f"  ✗ {step}: {err}", file=sys.stderr)


def guarded(log: Log, step: str, fn, default=None):
    try:
        return fn()
    except BudgetExceeded as e:
        log.fail(step, e)
    except Exception as e:  # keep going: a thinner audit beats no audit
        log.fail(step, e)
        if env("APA_DEBUG"):
            traceback.print_exc()
    return default


def collect(raw_input: str, marketplace: str | None, job_ad: Path | None, max_asins: int, top_n: int,
            n_category_terms: int) -> Path:
    load_env()
    budget, log = Budget(), Log()
    target = resolve(raw_input, marketplace)
    mp = target["marketplace"]
    has_keepa = bool(env("KEEPA_KEY"))

    # Brand unknown (ASIN or seller input): read it off a seed ASIN.
    if not target["brand"] and target["seed_asins"] and has_keepa:
        seed = guarded(log, "keepa.seed", lambda: keepa.fetch_products(target["seed_asins"][:1], mp, budget), [])
        if seed and seed[0].get("brand"):
            target["brand"] = seed[0]["brand"]

    out = run_dir(slug_for(target, dt.date.today().isoformat()))
    print(f"→ {target.get('brand') or target['input']} on {mp}  ({out})")
    write_json(out / "input.json", target)
    if job_ad:
        shutil.copy(job_ad, out / "job_ad.txt")

    # 1. ASIN map
    asins: list[str] = list(target["seed_asins"])
    if has_keepa:
        if target["brand"]:
            found = guarded(log, "keepa.brand", lambda: keepa.discover_by_brand(target["brand"], mp, budget), [])
            asins += found
            log.ok("keepa.brand", asins=len(found))
        if target["seller_id"]:
            seller = guarded(log, "keepa.seller", lambda: keepa.discover_by_seller(target["seller_id"], mp, budget), {})
            asins += seller.get("asins", [])
            target["seller_name"] = seller.get("seller_name")
    else:
        log.skip("keepa", "KEEPA_KEY not set")
    if catalog.configured() and target["brand"]:
        found = guarded(log, "spapi.search", lambda: catalog.search_brand(target["brand"], mp, budget), [])
        asins += found
        log.ok("spapi.search", asins=len(found))
    asins = list(dict.fromkeys(asins))
    discovered = len(asins)

    products = []
    if has_keepa and asins:
        products = guarded(log, "keepa.products", lambda: keepa.fetch_products(asins[:max_asins], mp, budget), [])
        log.ok("keepa.products", fetched=len(products), discovered=discovered)
    write_json(out / "keepa_products.json", {"discovered": discovered, "products": products})

    top = build_dataset.top_parents(products, top_n) or target["seed_asins"][:top_n]

    if catalog.configured() and top:
        items = guarded(log, "spapi.items", lambda: catalog.get_items(top, mp, budget), [])
        write_json(out / "catalog.json", items)
    else:
        log.skip("spapi.items", "SP-API not configured" if not catalog.configured() else "no ASINs")

    # 2. Sales + keywords
    keywords: list[dict] = []
    if junglescout.configured() and top:
        sales = {}
        for asin in top:
            sales[asin] = guarded(log, f"js.sales.{asin}", lambda a=asin: junglescout.sales_estimates(a, mp, budget), {})
        write_json(out / "js_sales.json", sales)
        keywords = guarded(log, "js.keywords", lambda: junglescout.keywords_by_asin(top, mp, budget), []) or []
        log.ok("js.keywords", keywords=len(keywords))
    elif dataforseo.configured() and top:
        log.skip("junglescout", "JS_KEY / JS_KEY_NAME not set; using DataForSEO ranked keywords")
        for asin in top[:5]:
            keywords += guarded(log, f"d4s.ranked.{asin}", lambda a=asin: dataforseo.ranked_keywords(a, mp, budget), []) or []
    else:
        log.skip("keywords", "no Jungle Scout or DataForSEO credentials")
    keywords = build_dataset.merge_keywords(keywords)
    write_json(out / "keywords.json", keywords)

    brand = (target.get("brand") or "").lower()
    brand_terms = [brand] if brand else []
    brand_terms += [k["keyword"] for k in keywords if brand and brand in k["keyword"] and k["keyword"] != brand][:2]
    category_terms = [k["keyword"] for k in keywords if not brand or brand not in k["keyword"]][:n_category_terms]

    # 3. Share of voice + live SERPs
    if junglescout.configured():
        sov = [s for s in (guarded(log, f"js.sov.{t}", lambda t=t: junglescout.share_of_voice(t, mp, budget))
                           for t in brand_terms[:1] + category_terms) if s]
        write_json(out / "js_sov.json", sov)
        log.ok("js.sov", keywords=len(sov))
    if dataforseo.configured():
        serps = [s for s in (guarded(log, f"d4s.serp.{t}", lambda t=t: dataforseo.serp(t, mp, budget))
                             for t in brand_terms + category_terms[:8]) if s]
        write_json(out / "serps.json", {"brand_terms": brand_terms, "serps": serps})
        log.ok("d4s.serp", keywords=len(serps))
    else:
        log.skip("d4s.serp", "DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD not set")

    # 4. CPC benchmark
    if ads_bench.configured(mp) and keywords:
        bids = guarded(log, "ads.bids", lambda: ads_bench.bid_recommendations(
            [k["keyword"] for k in keywords[:100]], mp, budget), {})
        write_json(out / "ads_bids.json", bids)
    else:
        log.skip("ads.bids", "Ads API not configured; using Jungle Scout PPC bids")

    write_json(out / "collect_log.json", {"steps": log.steps, "budget": budget.report(),
                                          "collected_at": dt.datetime.now(dt.UTC).isoformat()})
    dataset = build_dataset.build(out)
    write_json(out / "dataset.json", dataset)
    print(f"✓ dataset.json written. Budget: {budget.report()}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="ASIN, product URL, brand store URL, seller URL or brand name")
    ap.add_argument("--marketplace", choices=["us", "uk"], help="override; otherwise taken from the URL (default us)")
    ap.add_argument("--job-ad", type=Path, help="text file with the job advert")
    ap.add_argument("--max-asins", type=int, default=150, help="cap on ASINs pulled from Keepa (cost control)")
    ap.add_argument("--top-n", type=int, default=10, help="parents that get sales + keyword analysis")
    ap.add_argument("--category-terms", type=int, default=12)
    ap.add_argument("--rebuild", type=Path, help="skip collection; rebuild dataset.json for an existing run dir")
    args = ap.parse_args()

    if args.rebuild:
        write_json(args.rebuild / "dataset.json", build_dataset.build(args.rebuild))
        print(f"✓ rebuilt {args.rebuild / 'dataset.json'}")
        return
    if not args.input:
        ap.error("input is required unless --rebuild is given")
    collect(args.input, args.marketplace, args.job_ad, args.max_asins, args.top_n, args.category_terms)


if __name__ == "__main__":
    main()
