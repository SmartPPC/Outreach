"""Synthetic run directory for a fictional brand ("Brightpaw"), used by tests and for previewing the
audit page without API keys:  python -m tests.sample_run /tmp/sample && python -m analyse.render /tmp/sample
"""
from __future__ import annotations

import datetime as dt
import json
import random
import sys
from pathlib import Path

BRAND = "Brightpaw"


def _months(n: int) -> list[str]:
    today = dt.date.today().replace(day=1)
    out = []
    for i in range(n, 0, -1):
        y, m = divmod(today.month - 1 - i, 12)
        out.append(f"{today.year + y}-{m + 1:02d}")
    return out


def products() -> list[dict]:
    rnd = random.Random(7)
    lines = ["Dog Shampoo", "Puppy Shampoo", "Dog Paw Balm", "Dog Ear Cleaner", "Dog Dental Spray",
             "Cat Shampoo", "Dog Conditioner", "Dog Dry Shampoo", "Dog Wipes", "Dog Cologne"]
    out = []
    for i, line in enumerate(lines):
        for v in range(1 + (i < 3) * 2):
            asin = f"B0SAMPLE{i}{v}"
            listed = dt.date.today() - dt.timedelta(days=rnd.randint(60, 1000))
            months = _months(14)
            bsr0 = rnd.randint(800, 20000)
            out.append({
                "asin": asin, "parent_asin": f"B0PARENT{i:02d}" if i < 3 else asin,
                "title": f"{BRAND} {line} {['250ml', '500ml', 'Pack of 2'][v]} – Natural Oatmeal Formula for Sensitive Skin",
                "brand": BRAND, "category_path": ["Pet Supplies", "Dogs", "Grooming", LEAVES.get(i, "Grooming")],
                "root_category": "Pet Supplies",
                "listed_since": listed.isoformat(), "price": round(rnd.uniform(9, 24), 2),
                "monthly_sold": rnd.choice([None, 50, 100, 200, 400, 1000]) if i < 6 else None,
                "sales_rank": bsr0, "rating": round(rnd.uniform(3.8, 4.7), 1), "review_count": rnd.randint(5, 2400),
                "image_count": rnd.choice([4, 5, 6, 7, 9]), "video_count": rnd.choice([0, 0, 1]),
                "has_aplus": rnd.random() > 0.4, "aplus_modules": 4, "bullet_count": rnd.choice([3, 5, 5]),
                "bullet_avg_len": rnd.randint(60, 200), "title_len": 90, "description_len": 300,
                "variation_count": 3 if i < 3 else 0, "variation_dimensions": ["Size"] if i < 3 else [],
                "is_sns": i < 4, "brand_store": "Brightpaw",
                "list_price": 19.99, "offer_count": 2, "oos_pct_90": {0: 25, 2: 95}.get(i, 0),
                "history": {"bsr_monthly": {m: bsr0 * (1 + 0.02 * (14 - k)) for k, m in enumerate(months)},
                            "reviews_monthly": {m: 10 * k for k, m in enumerate(months)}},
                "source": "keepa",
            })
    return out


# Category leaf per product line; line 1 (puppy shampoo) is deliberately in the wrong category.
LEAVES = {0: "Shampoos & Conditioners", 1: "Dental Care", 2: "Shampoos & Conditioners", 6: "Shampoos & Conditioners"}


def js_catalog() -> list[dict]:
    """Jungle Scout-style catalogue: 3 best-seller families, a long tail, a duplicate, clutter and dead ASINs."""
    rows = []

    def row(asin, parent, title, revenue, units, **kw):
        rows.append({"asin": asin, "parent_asin": parent, "title": title, "brand": BRAND, "category": "Pet Supplies",
                     "price": 14.99, "units_30d": units, "revenue_30d": revenue, "sellers": kw.get("sellers", 1),
                     "buy_box_owner": kw.get("owner", "Amazon"), "available": kw.get("available", True),
                     "rating": 4.4, "reviews": kw.get("reviews", 500), "source": "junglescout"})

    for v in range(3):  # parent-level totals repeated on every child (a Jungle Scout quirk)
        row(f"B0SAMPLE0{v}", "B0PARENT00", f"{BRAND} Dog Shampoo {['250ml', '500ml', 'Pack of 2'][v]} – Oatmeal",
            30000, 2000, reviews=900 - v)
    for v, rev in enumerate((12000, 8000, 4000)):
        row(f"B0SAMPLE1{v}", "B0PARENT01", f"{BRAND} Puppy Shampoo {['250ml', '500ml', 'Pack of 2'][v]} – Tearless",
            rev, rev // 15, owner="PetDeals UK", sellers=7)
    for v, (title, rev) in enumerate((("Dog Shampoo 2-in-1 with Conditioner", 6000), ("Dog Conditioner Detangling", 5000),
                                      ("Dog Conditioner Travel Size", 1000))):
        row(f"B0SAMPLE2{v}", "B0PARENT02", f"{BRAND} {title}", rev, rev // 15)
    for i, rev in enumerate((3000, 2000, 1500, 1000, 500, 300, 100), start=3):
        row(f"B0SAMPLE{i}0", f"B0SAMPLE{i}0", f"{BRAND} {['Dog Ear Cleaner 100ml – Gentle Formula', 'Dog Dental Spray', 'Cat Shampoo', 'Dog Dry Shampoo', 'Dog Wipes', 'Dog Cologne', 'Paw Balm'][i - 3]}",
            rev, rev // 15)
    row("B0SAMPLE95", "B0SAMPLE95", f"{BRAND} Dog Ear Cleaner 100ml – Gentle Formula", 400, 25)
    row("B0SAMPLE96", "B0SAMPLE96", BRAND, 200, 12)
    row("B0SAMPLE97", "B0SAMPLE97", "Hundeshampoo mit Hafer für empfindliche Haut", 150, 9)
    for i in range(5):
        row(f"B0DEAD000{i}", f"B0DEAD000{i}", f"{BRAND} Discontinued Dog Shampoo {i}", 0, 0, available=False, sellers=0)
    return rows


def keywords_by_asin() -> dict:
    wasted = [{"keyword": "no 7 foundation", "volume": 9000, "organic_rank": None, "sponsored_rank": 5},
              {"keyword": "bright", "volume": 12000, "organic_rank": None, "sponsored_rank": 3}]
    return {"B0SAMPLE00": [{**k, "asin": "B0SAMPLE00"} for k in keywords() + wasted],
            "B0SAMPLE10": [{**k, "asin": "B0SAMPLE10"} for k in keywords()[:4]]}


def keywords() -> list[dict]:
    rows = [
        ("dog shampoo", 90000, 14, None, 1.45), ("puppy shampoo", 22000, 6, 3, 1.10),
        ("brightpaw", 3000, 1, None, 0.35), ("brightpaw dog shampoo", 900, 1, 1, 0.30),
        ("oatmeal dog shampoo", 15000, 9, None, 1.20), ("dog shampoo for itchy skin", 12000, 33, None, 1.35),
        ("paw balm for dogs", 18000, None, None, 1.05), ("dog ear cleaner", 25000, 48, 12, 1.25),
        ("dog conditioner", 8000, 22, None, 0.95), ("pawsome dog shampoo", 2500, None, None, 0.9),
        ("dog dental spray", 7000, None, 8, 1.15), ("natural dog shampoo sensitive skin", 4000, 4, None, 0.85),
    ]
    return [{"keyword": k, "volume": v, "organic_rank": o, "sponsored_rank": s, "relevancy": 0.5 + (i % 4) * 0.12,
             "cpc_exact": c, "source": "junglescout"} for i, (k, v, o, s, c) in enumerate(rows)]


def sov() -> list[dict]:
    def brands(mine: float, spons: float):
        return [{"brand": "Pawsome", "sov": 0.22, "organic_sov": 0.15, "sponsored_sov": 0.30, "sponsored_products": 6},
                {"brand": "Furlux", "sov": 0.14, "organic_sov": 0.12, "sponsored_sov": 0.18, "sponsored_products": 3},
                {"brand": BRAND, "sov": mine, "organic_sov": mine * 1.2, "sponsored_sov": spons, "sponsored_products": 1},
                {"brand": "CoatCare", "sov": 0.06, "organic_sov": 0.07, "sponsored_sov": 0.04, "sponsored_products": 1}]
    return [{"keyword": k, "volume_30d": v, "suggested_bid_median": 1.2, "brands": brands(m, s)}
            for k, v, m, s in [("dog shampoo", 90000, 0.05, 0.0), ("puppy shampoo", 22000, 0.11, 0.06),
                               ("oatmeal dog shampoo", 15000, 0.09, 0.0), ("dog ear cleaner", 25000, 0.03, 0.02)]]


def serps() -> dict:
    def item(asin, title, pos, sponsored, price=14.99, rating=4.4):
        return {"asin": asin, "title": title, "position": pos, "sponsored": sponsored,
                "type": "amazon_paid" if sponsored else "amazon_serp", "price": price, "rating": rating, "reviews": 900}
    return {"brand_terms": ["brightpaw"], "serps": [
        {"keyword": "brightpaw", "items": [
            item("B0COMP0001", "Pawsome Oatmeal Dog Shampoo 500ml", 1, True),
            item("B0SAMPLE00", f"{BRAND} Dog Shampoo 250ml", 2, False, 12.99, 4.3),
            item("B0COMP0002", "Furlux Puppy Shampoo Tearless", 3, True)]},
        {"keyword": "dog shampoo", "items": [
            item("B0COMP0001", "Pawsome Oatmeal Dog Shampoo 500ml", 1, True),
            item("B0COMP0003", "CoatCare Dog Shampoo", 2, False, 11.49, 4.6),
            item("B0COMP0004", "Furlux Dog Shampoo", 3, False, 13.99, 4.5),
            item("B0SAMPLE00", f"{BRAND} Dog Shampoo 250ml", 14, False, 16.99, 4.2)]},
    ]}


def findings() -> dict:
    return {
        "headline": "Brightpaw already ranks on page one for its biggest terms, but rivals own the ad slots above it, including on its own brand name.",
        "hero_actions": {"B0SAMPLE00": "Defend the brand term and push 'dog shampoo' from #14 to the top of page."},
        "points": [
            {"category": "advertising", "title": "Defend the Brightpaw brand search",
             "detail": "Pawsome and Furlux both run sponsored ads on 'brightpaw' searches and Brightpaw has no ad there. A brand SP + SB campaign costs pennies per click and keeps those shoppers.",
             "evidence": ["Pawsome sponsored at position 1 on 'brightpaw'", "No Brightpaw sponsored placement on its brand term"],
             "job_ad_quote": "protect and grow our brand on Amazon"},
            {"category": "advertising", "title": "Push 'dog shampoo' from #14 to the top of page",
             "detail": "It ranks organically at #14 for a 90,000-search term with no ad support. Exact-match SP at top of search would lift visibility while organic rank climbs.",
             "evidence": ["dog shampoo: 90,000 searches/mo, organic #14, no sponsored rank", "CPC benchmark £1.45"], "job_ad_quote": None},
            {"category": "content", "title": "Add video to the hero listings",
             "detail": "Most top listings have no video, which also rules out Sponsored Brands Video on the core terms.",
             "evidence": ["share_no_video from dataset"], "job_ad_quote": None},
        ],
        "catalogue_note": "Steady launches over the last three years, with the range concentrated in dog grooming.",
        "content_note": "Images and A+ are inconsistent across the top sellers; bullets are the strongest element.",
        "ad_strategy_summary": "Fund brand defence first, then the page-one 'push' terms in shampoo. The indicative budget below covers those terms only.",
        "amc_hypotheses": ["Grooming is a repeat category, so a sizeable share of buyers likely reorder within a few months.",
                           "With no SB or SD visible, the first touch in most journeys probably belongs to a competitor."],
        "amc_questions": ["How many ad touches come before a first purchase?", "What share of ad sales are new-to-brand?",
                          "How quickly do shampoo buyers reorder?"],
    }


def write(run: Path) -> Path:
    run.mkdir(parents=True, exist_ok=True)
    prods = products()
    sales = {}
    for p in prods[:6]:
        sales[p["asin"]] = {m: {"units": 300 + 20 * k, "revenue": (300 + 20 * k) * p["price"]}
                            for k, m in enumerate(_months(13))}
    files = {
        "input.json": {"input": BRAND, "brand": BRAND, "marketplace": "uk", "seed_asins": [], "seller_id": None},
        "keepa_products.json": {"discovered": len(prods) + 4, "products": prods},
        "js_catalog.json": js_catalog(), "keywords_by_asin.json": keywords_by_asin(),
        "js_sales.json": sales, "keywords.json": keywords(), "js_sov.json": sov(), "serps.json": serps(),
        "collect_log.json": {"steps": [{"step": "spapi.items", "status": "skipped", "reason": "SP-API not configured"}]},
        "findings.json": findings(),
    }
    for name, data in files.items():
        (run / name).write_text(json.dumps(data, indent=2))
    return run


if __name__ == "__main__":
    from analyse import build_dataset

    run = write(Path(sys.argv[1]))
    (run / "dataset.json").write_text(json.dumps(build_dataset.build(run), indent=2))
    print(run)
