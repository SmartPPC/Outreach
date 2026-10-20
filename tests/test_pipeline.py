import json

from analyse import build_dataset, render
from analyse.rubric import check_listing
from collectors import ads_bench, dataforseo, junglescout, keepa
from collectors.resolve import resolve
from tests import sample_run


# --- resolve -------------------------------------------------------------------------------------

def test_resolve_product_url():
    t = resolve("https://www.amazon.co.uk/Some-Product/dp/B0ABCDEF12/ref=sr_1_1?th=1")
    assert t["marketplace"] == "uk" and t["seed_asins"] == ["B0ABCDEF12"]


def test_resolve_store_url():
    t = resolve("https://www.amazon.com/stores/Brightpaw/page/1A2B3C4D-1111-2222-3333-444455556666?ref_=ast_bln")
    assert t["brand"] == "Brightpaw" and t["marketplace"] == "us"


def test_resolve_seller_and_brand_and_asins():
    assert resolve("https://www.amazon.co.uk/s?me=A1B2C3D4E5F6G7")["seller_id"] == "A1B2C3D4E5F6G7"
    assert resolve("Brightpaw", "uk")["brand"] == "Brightpaw"
    assert resolve("B0ABCDEF12, B0ABCDEF13")["seed_asins"] == ["B0ABCDEF12", "B0ABCDEF13"]


# --- parsers -------------------------------------------------------------------------------------

def test_keepa_parse_product():
    t0 = 7_000_000  # keepa minutes
    raw = {
        "asin": "B0X", "parentAsin": "B0P", "title": "T" * 120, "brand": "Brightpaw",
        "images": [{}, {}, {}, {}, {}, {}, {}], "videos": [{}], "aPlus": [{"module": 1}],
        "features": ["a" * 150] * 5, "listedSince": t0, "isSNS": True,
        "categoryTree": [{"name": "Pet Supplies"}, {"name": "Dogs"}],
        "csv": [[t0, 1299], None, None, [t0, 5000, t0 + 60 * 24 * 40, 4000]] + [None] * 12
               + [[t0, 45], [t0, 120, t0 + 100, 130]],
        "stats": {"current": [1299, 1399]},
        "variations": [{"asin": "B0X", "attributes": [{"dimension": "Size", "value": "250ml"}]}],
    }
    p = keepa.parse_product(raw)
    assert p["price"] == 12.99 and p["sales_rank"] == 4000 and p["rating"] == 4.5 and p["review_count"] == 130
    assert p["image_count"] == 7 and p["video_count"] == 1 and p["has_aplus"] and p["is_sns"]
    assert p["variation_dimensions"] == ["Size"] and p["listed_since"].startswith("2024")
    assert check_listing(p)["score"] == 100


def test_junglescout_parsers():
    kw = junglescout.parse_keywords({"data": [{"id": "us/dog shampoo", "attributes": {
        "name": "dog shampoo", "monthly_search_volume_exact": 90000, "organic_rank": 14, "ppc_bid_exact": 1.45}}]})
    assert kw[0]["keyword"] == "dog shampoo" and kw[0]["cpc_exact"] == 1.45
    sov = junglescout.parse_sov("dog shampoo", {"data": {"attributes": {"estimated_30_day_search_volume": 9,
        "brands": [{"brand": "A", "combined_weighted_sov": 0.1}, {"brand": "B", "combined_weighted_sov": 0.3}]}}})
    assert [b["brand"] for b in sov["brands"]] == ["B", "A"]
    sales = junglescout.parse_sales({"data": [{"attributes": {"data": [
        {"date": "2026-08-01", "estimated_units_sold": 10, "last_known_price": 2.0},
        {"date": "2026-08-02", "estimated_units_sold": 5, "last_known_price": 2.0}]}}]})
    assert sales == {"2026-08": {"units": 15, "revenue": 30.0}}


def test_dataforseo_and_ads_parsers():
    serp = dataforseo.parse_serp("x", {"tasks": [{"result": [{"items": [
        {"type": "amazon_paid", "data_asin": "B1", "rank_absolute": 1, "title": "A"},
        {"type": "amazon_serp", "data_asin": "B2", "rank_absolute": 2, "title": "B", "rating": {"value": 4.5}}]}]}]})
    assert [i["sponsored"] for i in serp["items"]] == [True, False]
    bids = ads_bench.parse_bids({"bidRecommendations": [{"bidRecommendationsForTargetingExpressions": [
        {"targetingExpression": {"value": "dog shampoo"}, "bidValues": [{"suggestedBid": 1.6}, {"suggestedBid": 0.9}, {"suggestedBid": 1.2}]}]}]})
    assert bids["dog shampoo"] == {"low": 0.9, "suggested": 1.2, "high": 1.6}


def test_merge_keywords_keeps_best_rank():
    merged = build_dataset.merge_keywords([
        {"keyword": "Dog Shampoo", "volume": 10, "organic_rank": 20, "sponsored_rank": None},
        {"keyword": "dog shampoo", "volume": 12, "organic_rank": 9, "sponsored_rank": 4, "cpc_exact": 1.0}])
    assert merged == [{"keyword": "dog shampoo", "volume": 12, "organic_rank": 9, "sponsored_rank": 4, "cpc_exact": 1.0}]


# --- end to end on the synthetic run ------------------------------------------------------------

def test_build_and_render(tmp_path):
    run = sample_run.write(tmp_path / "brightpaw-uk-2026-10-20")
    d = build_dataset.build(run)
    json.dumps(d)  # serialisable

    assert d["asin_map"]["parents"] == 10
    assert d["catalogue"]["launches_last_12m"] >= 0
    assert d["content"]["top_parents"] and all(0 <= p["score"] <= 100 for p in d["content"]["top_parents"])

    attackers = {a["brand_guess"].split()[0] for a in d["competitors"]["brand_term_attackers"]}
    assert attackers == {"Pawsome", "Furlux"}
    assert d["competitors"]["prospect_sponsored_on_own_brand"] is False

    kmap = {k["keyword"]: k for k in d["strategy"]["keyword_map"]}
    assert kmap["dog shampoo"]["status"] == "push"
    assert kmap["brightpaw"]["tier"] == "brand" and kmap["brightpaw"]["status"] == "brand_defence_gap"
    assert kmap["pawsome dog shampoo"]["tier"] == "competitor"
    assert kmap["paw balm for dogs"]["status"] == "missing"
    assert d["strategy"]["budget"]["monthly_total"] > 0
    assert d["strategy"]["repeat_signals"]["likelihood"] == "high"

    (run / "dataset.json").write_text(json.dumps(d))
    html_path, md_path = render.render(run)
    page = html_path.read_text()
    assert "{{" not in page and "Brightpaw" in page and "Defend the Brightpaw brand search" in page
    assert "Pawsome" in md_path.read_text() or "Defend" in md_path.read_text()
