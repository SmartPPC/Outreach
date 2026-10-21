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

from analyse import build_dataset, checks
from collectors import ads_bench, catalog, contacts, dataforseo, images, junglescout, keepa
from collectors.common import Budget, BudgetExceeded, env, load_env, run_dir, write_json
from collectors.resolve import brand_spellings, resolve, slug_for


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
            n_category_terms: int, website: str | None = None, brand: str | None = None,
            asin_only: bool = False) -> Path:
    load_env()
    budget, log = Budget(), Log()
    target = resolve(raw_input, marketplace)
    if brand:  # the store URL slug can mislead (e.g. "UltraDEX"); the user's spelling wins
        target["brand"] = brand
    mp = target["marketplace"]
    has_keepa = bool(env("KEEPA_KEY"))
    if has_keepa:
        status = guarded(log, "keepa.token", keepa.token_status, {})
        if status:
            log.ok("keepa.token", tokens_left=status.get("left"), per_minute=status.get("rate"))

    # Brand unknown (ASIN or seller input): read it off a seed ASIN.
    seed: list[dict] = []
    if asin_only:
        target["scope"] = "asin"
    if not target["brand"] and target["seed_asins"] and has_keepa:
        seed = guarded(log, "keepa.seed", lambda: keepa.fetch_products(target["seed_asins"][:1], mp, budget), [])
        if seed and seed[0].get("brand"):
            target["brand"] = seed[0]["brand"]

    out = run_dir(slug_for(target, dt.date.today().isoformat()))
    print(f"→ {target.get('brand') or target['input']} on {mp}  ({out})")
    if job_ad:
        shutil.copy(job_ad, out / "job_ad.txt")

    # 1. Catalogue. Jungle Scout maps the whole range cheaply; Keepa (token-limited) is kept for the
    #    best-sellers that make ~80% of revenue.
    catalog_rows: list[dict] = []
    if junglescout.configured() and target["brand"]:
        spellings = brand_spellings(target["brand"], target.get("brand_slug"))
        catalog_rows = guarded(log, "js.catalog", lambda: junglescout.product_database(
            target["brand"], mp, budget, alt_spellings=spellings[1:]), []) or []
        log.ok("js.catalog.spellings", searched=spellings)
        write_json(out / "js_catalog.json", catalog_rows)
        log.ok("js.catalog", asins=len(catalog_rows))
        brands = [r["brand"] for r in catalog_rows if r.get("brand")]
        if brands:  # canonical spelling, e.g. store slug "SuperFacialist" -> "Super Facialist"
            target["brand"] = max(set(brands), key=brands.count)
    write_json(out / "input.json", target)

    products: list[dict] = []
    if catalog_rows:
        discovered = len(catalog_rows)
        focus = checks.select_heroes(catalog_rows, max_families=top_n)
    else:
        log.skip("js.catalog", "Jungle Scout unavailable; mapping the catalogue with Keepa (slow on small plans)")
        asins: list[str] = list(target["seed_asins"])
        if has_keepa and target["brand"]:
            asins += guarded(log, "keepa.brand", lambda: keepa.discover_by_brand(target["brand"], mp, budget), []) or []
        if has_keepa and target["seller_id"]:
            seller = guarded(log, "keepa.seller", lambda: keepa.discover_by_seller(target["seller_id"], mp, budget), {}) or {}
            asins += seller.get("asins", [])
            target["seller_name"] = seller.get("seller_name")
        if catalog.configured() and target["brand"]:
            asins += guarded(log, "spapi.search", lambda: catalog.search_brand(target["brand"], mp, budget), []) or []
        asins = list(dict.fromkeys(asins))
        discovered = len(asins)
        if has_keepa and asins:
            products = guarded(log, "keepa.products", lambda: keepa.fetch_products(asins[:max_asins], mp, budget), []) or []
        focus = checks.select_heroes(build_dataset.catalog_from_keepa(products), max_families=top_n)

    if target.get("scope") == "asin" and target["seed_asins"]:
        # Single-product audit: only the given ASIN's family, with that ASIN as the lead
        focus = checks.focus_on_asin(catalog_rows or build_dataset.catalog_from_keepa(products or seed),
                                     target["seed_asins"][0], seed[0] if seed else None)

    heroes = [h["asin"] for h in focus["heroes"]] or target["seed_asins"][:1]
    log.ok("focus", live=focus["live_asins"], hero_families=focus["hero_families"],
           revenue_share=focus["hero_revenue_share"])

    if catalog_rows and has_keepa and heroes:
        variants = list(dict.fromkeys(a for h in focus["heroes"] for a in [h["asin"], *h["children"][:2]]))[:30]
        products = guarded(log, "keepa.heroes", lambda: keepa.fetch_products(variants, mp, budget), []) or []
        log.ok("keepa.heroes", fetched=len(products), waited_min=keepa.waited_minutes())
    elif not has_keepa:
        log.skip("keepa", "KEEPA_KEY not set")
    write_json(out / "keepa_products.json", {"discovered": discovered, "products": products})

    # Phone-size image sheets for the best-sellers (needs m.media-amazon.com in Allowed domains)
    keepa_by_asin = {p["asin"]: p for p in products}
    sheets = 0
    for h in focus["heroes"]:
        lead = keepa_by_asin.get(build_dataset._live_lead(h, keepa_by_asin))
        if not lead or not lead.get("images_detail"):
            continue
        try:
            if images.phone_sheet(lead["images_detail"], out / "mobile" / f"{lead['asin']}.png"):
                sheets += 1
        except images.ImagesBlocked as e:
            log.skip("images", str(e))
            break
        except Exception as e:  # noqa: BLE001 - a missing sheet only loses the legibility check
            log.fail("images", e)
            break
    if sheets:
        log.ok("images", sheets=sheets)

    if catalog.configured() and heroes:
        items = guarded(log, "spapi.items", lambda: catalog.get_items(heroes, mp, budget), [])
        write_json(out / "catalog.json", items)
    else:
        log.skip("spapi.items", "SP-API not configured" if not catalog.configured() else "no ASINs")

    # 2. Keywords per best-seller (ranks, sponsored terms, wasted spend)
    per_asin: dict[str, list[dict]] = {}
    if junglescout.configured():
        for asin in heroes:
            per_asin[asin] = guarded(log, f"js.keywords.{asin}",
                                     lambda a=asin: junglescout.keywords_for_asin(a, mp, budget), []) or []
    elif dataforseo.configured():
        for asin in heroes[:5]:
            per_asin[asin] = [{**r, "asin": asin} for r in guarded(
                log, f"d4s.ranked.{asin}", lambda a=asin: dataforseo.ranked_keywords(a, mp, budget), []) or []]
    else:
        log.skip("keywords", "no Jungle Scout or DataForSEO credentials")
    write_json(out / "keywords_by_asin.json", per_asin)
    keywords = build_dataset.merge_keywords([r for rows in per_asin.values() for r in rows])
    write_json(out / "keywords.json", keywords)
    log.ok("keywords", heroes=len(per_asin), keywords=len(keywords))

    brand = (target.get("brand") or "").lower()
    brand_terms = list(dict.fromkeys(t for t in (brand, brand.replace(" ", "")) if t))
    brand_terms += [k["keyword"] for k in keywords
                    if build_dataset._has_brand(k["keyword"], brand) and k["keyword"] not in brand_terms][:1]
    category_terms = [k["keyword"] for k in keywords if not build_dataset._has_brand(k["keyword"], brand)][:n_category_terms]

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

    # 5. Contacts published on the brand's own site (kept out of the shareable audit page)
    if dataforseo.configured() and target.get("brand"):
        found = guarded(log, "contacts", lambda: contacts.find_contacts(target["brand"], budget, website), {}) or {}
        owners = [r.get("buy_box_owner") for r in catalog_rows if r.get("buy_box_owner")]
        seller = max(set(owners), key=owners.count) if owners else None
        found = guarded(log, "contacts.research",
                        lambda: contacts.research(target["brand"], mp, budget, found, seller), found) or found
        write_json(out / "contacts.json", found)
        log.ok("contacts", website=found.get("website"), emails=len(found.get("emails") or []))
    else:
        log.skip("contacts", "DataForSEO not configured")

    write_json(out / "input.json", target)
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
    ap.add_argument("--top-n", type=int, default=12, help="max best-seller families analysed in depth")
    ap.add_argument("--category-terms", type=int, default=12)
    ap.add_argument("--asin-only", action="store_true",
                    help="audit just the given ASIN's product family (automatic for a bare ASIN)")
    ap.add_argument("--brand", help="override the brand name read from the URL (use the spelling on Amazon)")
    ap.add_argument("--website", help="brand website for contact finding (otherwise <brand>.co.uk/.com/.co is tried)")
    ap.add_argument("--rebuild", type=Path, help="skip collection; rebuild dataset.json for an existing run dir")
    args = ap.parse_args()

    if args.rebuild:
        write_json(args.rebuild / "dataset.json", build_dataset.build(args.rebuild))
        print(f"✓ rebuilt {args.rebuild / 'dataset.json'}")
        return
    if not args.input:
        ap.error("input is required unless --rebuild is given")
    collect(args.input, args.marketplace, args.job_ad, args.max_asins, args.top_n, args.category_terms, args.website, args.brand,
            args.asin_only)


if __name__ == "__main__":
    main()
