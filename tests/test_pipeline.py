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


def test_single_asin_scope_and_focus():
    from analyse import checks
    from collectors.resolve import slug_for
    t = resolve("B0GTRFKFV5", "uk")
    assert t["scope"] == "asin" and slug_for({**t, "brand": "Acme"}, "2026-10-21") == "acme-b0gtrfkfv5-uk-2026-10-21"
    assert resolve("https://www.amazon.co.uk/stores/X/page/1A2B3C4D-1111-2222-3333-444455556666")["scope"] == "brand"
    catalog = sample_run.js_catalog()
    f = checks.focus_on_asin(catalog, "B0SAMPLE11")
    assert f["scope"] == "asin" and len(f["heroes"]) == 1
    assert f["heroes"][0]["asin"] == "B0SAMPLE11" and f["heroes"][0]["parent_asin"] == "B0PARENT01"
    assert f["est_monthly_revenue"] == 24000 and f["brand_monthly_revenue"] > 24000


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


def test_proxy_auth_enables_provider_without_local_keys(monkeypatch):
    for k in ("JS_KEY", "JS_KEY_NAME", "DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD", "APA_PROXY_AUTH"):
        monkeypatch.delenv(k, raising=False)
    assert not junglescout.configured() and not dataforseo.configured()
    monkeypatch.setenv("APA_PROXY_AUTH", "junglescout, dataforseo")
    assert junglescout.configured() and dataforseo.configured()
    assert "Authorization" not in junglescout._headers() and dataforseo._headers() == {}
    monkeypatch.setenv("JS_KEY_NAME", "n")
    monkeypatch.setenv("JS_KEY", "k")
    assert junglescout._headers()["Authorization"] == "n:k"


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


# --- v2: best-seller focus, checks, Keepa pacing --------------------------------------------------

def test_store_url_landing_asin_and_brand_spacing():
    t = resolve("https://www.amazon.co.uk/stores/SuperFacialist/page/4DCB54EE-A8CD-4785-9118-273A1D6CBDD4"
                "?lp_asin=B0D6BWBYY2&ref_=ast_bln")
    assert t["brand"] == "Super Facialist" and t["seed_asins"] == ["B0D6BWBYY2"] and t["marketplace"] == "uk"
    assert resolve("https://www.amazon.co.uk/stores/UltraDEX/page/02885511-9448-4D57-A25F-B3812F09FE2C")["brand"] == "UltraDEX"
    from collectors.resolve import brand_spellings
    assert brand_spellings("UltraDEX") == ["UltraDEX", "Ultra DEX"]
    assert brand_spellings("Super Facialist", "SuperFacialist") == ["Super Facialist", "SuperFacialist"]
    assert build_dataset._has_brand("Superfacialist Rose Miracle Makeover Facial Oil", "Super Facialist")


def test_heroes_cover_80_percent_and_skip_dead_listings():
    from analyse import checks
    focus = checks.select_heroes(sample_run.js_catalog())
    assert [h["parent_asin"] for h in focus["heroes"]] == ["B0PARENT00", "B0PARENT01", "B0PARENT02"]
    assert focus["heroes"][0]["revenue_30d"] == 30000  # repeated parent total counted once
    assert focus["hero_revenue_share"] >= 0.8
    assert focus["live_asins"] == focus["total_asins"] - 5


def test_hero_flags_quick_wins_and_wasted_terms(tmp_path):
    d = build_dataset.build(sample_run.write(tmp_path / "brightpaw-uk-2026-10-20"))
    heroes = {h["parent_asin"]: h for h in d["heroes"]}  # the lead variant is whichever Keepa sees selling
    flag_types = lambda parent: {f["type"] for f in heroes[parent]["flags"]}  # noqa: E731

    assert "wrong_category" in flag_types("B0PARENT01")
    assert "sellers" in flag_types("B0PARENT01")                     # reseller holds the Buy Box, 7 sellers
    assert "mixed_variation_family" in flag_types("B0PARENT02")
    assert "stock" in flag_types("B0PARENT00")                       # 25% out of stock: lost sales
    assert "stock" not in flag_types("B0PARENT02")                   # 95%: reads as discontinued, ignored

    lead = heroes["B0PARENT00"]
    if lead["asin"] == "B0SAMPLE00":
        wasted = {w["keyword"]: w["reason"] for w in lead["wasted_terms"]}
        assert wasted == {"no 7 foundation": "unrelated to the product", "bright": "partial brand term"}
        assert any(t["keyword"] == "dog shampoo" and t["status"] == "push" for t in lead["targets"])

    q = d["quick_wins"]
    assert [sorted(g["asin"] for g in grp) for grp in q["duplicates"]] == [["B0SAMPLE30", "B0SAMPLE95"]]
    assert {c["asin"] for c in q["clutter"]} == {"B0SAMPLE96", "B0SAMPLE97"}
    surfaced = json.dumps([d["heroes"], d["quick_wins"]])
    assert "B0DEAD" not in surfaced


def test_keepa_waits_for_tokens_instead_of_failing(monkeypatch):
    slept = []
    monkeypatch.setattr(keepa, "_sleep", slept.append)
    monkeypatch.setattr(keepa, "_state", {"left": 1, "rate": 1, "refill_in_ms": 30_000, "waited_s": 0.0})
    calls = []

    def fake_http(method, url, params=None, **kw):
        calls.append(params["asin"])
        return {"products": [], "tokensLeft": 0, "refillRate": 1, "refillIn": 60_000, "tokensConsumed": 2}

    monkeypatch.setattr(keepa, "http_json", fake_http)
    monkeypatch.setenv("KEEPA_KEY", "k")
    from collectors.common import Budget
    keepa.fetch_products(["B01", "B02"], "uk", Budget())
    assert calls == ["B01", "B02"]          # one ASIN per call while the bucket is nearly empty
    assert slept and sum(slept) < 10 * 60    # waited for refills rather than raising


def test_keepa_gives_up_past_max_wait(monkeypatch):
    import pytest
    monkeypatch.setattr(keepa, "_sleep", lambda s: None)
    monkeypatch.setattr(keepa, "_state", {"left": 0, "rate": 1, "refill_in_ms": 60_000, "waited_s": 0.0})
    monkeypatch.setattr(keepa, "MAX_WAIT_S", 60)
    with pytest.raises(RuntimeError, match="APA_KEEPA_MAX_WAIT_MIN"):
        keepa._wait_for(10)


def test_amazon_held_buy_box_raises_no_price_or_seller_flags():
    from analyse import checks
    p = {"price": 2.35, "list_price": 7.16, "sellers": 8, "buy_box_owner": "Amazon"}
    assert checks.seller_flags(p, "UltraDEX") == [] and checks.price_flag(p) is None
    reseller = {**p, "buy_box_owner": "Cheap Deals UK"}
    assert len(checks.seller_flags(reseller, "UltraDEX")) == 2 and checks.price_flag(reseller)


def test_own_brand_terms_are_never_wasted():
    from analyse import checks
    kws = [{"keyword": "ultradex toothpaste", "sponsored_rank": 9, "organic_rank": None, "volume": 766},
           {"keyword": "ultra dex", "sponsored_rank": 14, "organic_rank": None, "volume": 599},
           {"keyword": "otrivine", "sponsored_rank": 1, "organic_rank": None, "volume": 3481}]
    assert [w["keyword"] for w in checks.wasted_terms("UltraDEX Daily Oral Rinse 500ml", "UltraDEX", kws)] == ["otrivine"]


def test_family_revenue_counts_repeated_parent_units_once():
    from analyse import checks
    kids = [{"units_30d": 879, "revenue_30d": 879 * price, "price": price} for price in (12.0, 16.0, 20.0)]
    assert checks.family_revenue(kids) == 879 * 12.0
    near = [{"units_30d": u, "revenue_30d": r, "price": p}
            for u, r, p in ((879, 26370, 30), (879, 17580, 20), (830, 13280, 16), (882, 12348, 14))]
    assert checks.family_revenue(near) == 882 * 14
    # UltraDEX: a 6-pack given the single's units must not count as 6x the revenue
    rinse = [{"units_30d": 3381, "revenue_30d": 136829, "price": 40.47}, {"units_30d": 2340, "revenue_30d": 37440, "price": 16.0},
             {"units_30d": 3381, "revenue_30d": 19238, "price": 5.69}]
    assert round(checks.family_revenue(rinse)) == round(3381 * 5.69)
    spray = [{"units_30d": 5441, "revenue_30d": 153436, "price": 28.2}, {"units_30d": 5432, "revenue_30d": 12765, "price": 2.35},
             {"units_30d": 4472, "revenue_30d": 10509, "price": 2.35}]
    assert round(checks.family_revenue(spray)) == round(5441 * 2.35)
    assert checks.family_revenue([{"units_30d": 10, "revenue_30d": 100}, {"units_30d": 5, "revenue_30d": 50}]) == 150


def test_archive_keeps_deliverables_and_one_index_row(tmp_path):
    from analyse import archive
    run = sample_run.write(tmp_path / "runs" / "brightpaw-uk-2026-10-20")
    (run / "dataset.json").write_text(json.dumps(build_dataset.build(run)))
    render.render(run)
    (run / "email.md").write_text("Hi,\n\n1. **Wrong category.** Moved.\n2. **Wasted ads.** Cut.\n")
    audits = tmp_path / "audits"
    dest = archive.archive(run, "https://claude.ai/artifact/x", audits)
    archive.archive(run, "https://claude.ai/artifact/x", audits)  # re-archive must not duplicate

    assert {"email.md", "audit.html", "findings.json", "evidence.md", "dataset.json", "README.md"} <= {p.name for p in dest.iterdir()}
    assert not (dest / "keepa_products.json").exists() and not (dest / "js_catalog.json").exists()
    assert "1. Wrong category. Moved." in (dest / "README.md").read_text()
    index = (audits / "INDEX.md").read_text()
    assert index.count("[brightpaw-uk-2026-10-20]") == 1 and "https://claude.ai/artifact/x" in index


def test_lead_variant_is_the_one_keepa_sees_selling():
    keepa_by_asin = {a: {"asin": a, **k} for a, k in {
        "A1": {"price": None, "monthly_sold": None},                  # JS credits it, but no live offer
        "A2": {"price": 90.0, "monthly_sold": 100, "sales_rank": 900},
        "A3": {"price": 160.0, "monthly_sold": 50, "sales_rank": 500}}.items()}
    hero = {"asin": "A1", "children": ["A1", "A2", "A3"]}
    assert build_dataset._live_lead(hero, keepa_by_asin) == "A2"
    assert build_dataset._live_lead({"asin": "A1", "children": ["A1"]}, {}) == "A1"


# --- contacts ---------------------------------------------------------------------------------------

PAGE = """Our Story. Brightpaw was founded by Jane Holloway in 2019.
Jane Holloway, Founder. Tom Reeve - Director.
SHIP RIGHTS OVER the goods remain ours.
For trade enquiries email wholesale@brightpaw.co.uk or jane.holloway@brightpaw.co.uk.
Customer care: hello@brightpaw.co.uk, complaints@brightpaw.co.uk.
This website is operated by Brightpaw Trading Ltd, company number 12345678."""


def test_contact_extraction_and_ranking():
    from collectors import contacts
    x = contacts.extract(PAGE)
    assert set(x["people"]) == {"Jane Holloway", "Tom Reeve"}            # all-caps text isn't a name
    assert x["company_number"] == "12345678" and x["company_name"] == "Brightpaw Trading Ltd"
    people = x["people"]
    assert contacts.classify("jane.holloway@brightpaw.co.uk", people) == "personal"
    assert contacts.classify("wholesale@brightpaw.co.uk", people) == "business"
    assert contacts.classify("complaints@brightpaw.co.uk", people) == "generic"
    assert contacts._generic_rank("hello@x.co") < contacts._generic_rank("complaints@x.co")


def test_suggested_addresses_only_from_a_published_format():
    from collectors import contacts
    people = {"Jane Holloway": "founder", "Tom Reeve": "director"}
    fmt = contacts.email_format(["jane.holloway@brightpaw.co.uk"], people, "brightpaw.co.uk")
    assert fmt == "{first}.{last}"
    sugg = contacts.suggest(people, fmt, "brightpaw.co.uk", {"jane.holloway@brightpaw.co.uk"})
    assert sugg == [{"name": "Tom Reeve", "email": "tom.reeve@brightpaw.co.uk",
                     "status": "unverified guess, check before sending"}]
    assert contacts.email_format(["hello@brightpaw.co.uk"], people, "brightpaw.co.uk") is None
    assert contacts.suggest(people, None, "brightpaw.co.uk", set()) == []


def test_contacts_never_reach_the_shared_audit_page(tmp_path):
    run = sample_run.write(tmp_path / "brightpaw-uk-2026-10-20")
    (run / "contacts.json").write_text(json.dumps({"website": "https://brightpaw.co.uk",
                                                   "emails": [{"email": "jane@brightpaw.co.uk", "type": "personal",
                                                               "source": "x", "on_domain": True}]}))
    (run / "dataset.json").write_text(json.dumps(build_dataset.build(run)))
    html_path, _ = render.render(run)
    assert "jane@brightpaw.co.uk" not in html_path.read_text()


def test_companies_house_keeps_exact_active_matches_only():
    from collectors import contacts
    text = ("13185686 - Dissolved on 11 April 2023\n99 Gainsborough Crescent, Eastbourne, BN23 7NL\nVANETTI LTD\n"
            "12345678 - Incorporated on 2 March 2021\n86 Paul St, London, EC2A 4NE\nVANETTI LIMITED\n"
            "87654321 - Incorporated on 1 May 2020\n1 High St, Leeds\nVANETTI HOLDINGS LTD\n")
    found = contacts.parse_ch_search(text, "vanetti")
    assert [(c["number"], c["active"]) for c in found] == [("13185686", False), ("12345678", True)]


def test_org_names_and_linkedin_links():
    from collectors import contacts
    orgs = contacts.org_names("BESQUE", "HBL Ventures LLC", "Amazon")
    assert [o["name"] for o in orgs] == ["BESQUE", "HBL Ventures LLC"]   # Amazon as seller isn't an org lead
    links = contacts.linkedin_links(orgs)
    assert len(links) == 8 and links[0]["url"].startswith("https://www.linkedin.com/search/results/people/?keywords=")


def test_apollo_parsing_ranking_and_exact_org_match():
    from collectors import apollo
    people = apollo.parse_people({"people": [
        {"id": "1", "name": "Sam Lee", "title": "Social Media Executive", "organization": {"name": "Besque"}},
        {"id": "2", "name": "Ana Cruz", "title": "Head of Ecommerce", "organization": {"name": "Besque"},
         "linkedin_url": "https://linkedin.com/in/ana"},
        {"id": "3", "name": "Joe Hart", "title": "Co-Founder & CEO", "organization": {"name": "HBL Ventures"}}]})
    assert [p["name"] for p in people] == ["Joe Hart", "Ana Cruz", "Sam Lee"]
    orgs = apollo.parse_orgs({"organizations": [{"id": "a", "name": "HBL Ventures LLC", "primary_domain": "besque.co"},
                                                {"id": "b", "name": "HBL Ventures Partners"}]}, "HBL Ventures")
    assert [o["id"] for o in orgs] == ["a"]


def test_apollo_enriches_only_the_top_people(monkeypatch):
    from collectors import apollo
    from collectors.common import Budget
    monkeypatch.setattr(apollo, "find_orgs", lambda name, budget: [])
    monkeypatch.setattr(apollo, "search_people", lambda budget, domains=None, org_ids=None: [
        {"id": str(i), "name": f"P{i}", "title": t, "rank": apollo.rank(t), "email": None}
        for i, t in enumerate(["Founder", "Ecommerce Manager", "Marketing Lead", "Intern"])])
    calls = []
    monkeypatch.setattr(apollo, "enrich", lambda pid, budget: calls.append(pid) or
                        {"email": f"p{pid}@besque.co", "email_status": "verified"})
    out = apollo.people_for([], "besque.co", Budget(), enrich_top=2)
    assert calls == ["0", "1"] and out["people"][0]["email"] == "p0@besque.co"


# --- mobile -----------------------------------------------------------------------------------------

def test_mobile_checks():
    from analyse import mobile
    p = {"title": "Brightpaw Dog Shampoo 250ml – Oatmeal", "has_aplus": True,
         "images_detail": [{"w": 2000, "h": 2000}] * 6 + [{"w": 900, "h": 900}],
         "videos_detail": [{"creator": "Influencer", "duration": 40}],
         "features": ["Gentle oatmeal formula for itchy skin", "x" * 300],
         "aplus_alt": ["Text reads 'Soothes'", "Text reads '" + " ".join(["word"] * 35) + "'"]}
    c = mobile.check(p, "Brightpaw")["checks"]
    assert c["zoom"]["status"] == "fail" and "1 of 7" in c["zoom"]["detail"]
    assert c["video"]["status"] == "warn" and "no brand-made video" in c["video"]["detail"]
    assert c["title_on_mobile"]["status"] == "good"
    assert c["bullets_on_mobile"]["status"] == "warn"
    assert c["a_plus_on_mobile"]["status"] == "warn"
    long_title = "Brightpaw " + "natural gentle soothing calming nourishing " * 3 + "Dog Shampoo 250ml"
    assert mobile.check({"title": long_title}, "Brightpaw")["checks"]["title_on_mobile"]["status"] == "fail"
    assert mobile.text_words("Text reads &#39;86% Saw Firmness&#39; and &#39;Full Body&#39;") == 5


def test_phone_sheet_skips_cleanly_when_images_are_blocked(tmp_path):
    from collectors import images
    import pytest

    def blocked(file):
        raise images.ImagesBlocked("blocked")
    with pytest.raises(images.ImagesBlocked):
        images.phone_sheet([{"medium": "a.jpg"}], tmp_path / "s.png", fetcher=blocked)


def test_phone_sheet_builds_from_images(tmp_path):
    import io
    from PIL import Image
    from collectors import images
    buf = io.BytesIO()
    Image.new("RGB", (500, 500), "red").save(buf, "JPEG")
    out = images.phone_sheet([{"medium": "a.jpg", "variant": "MAIN"}, {"medium": "b.jpg", "variant": "PT01"}],
                             tmp_path / "s.png", fetcher=lambda f: buf.getvalue())
    assert out and Image.open(out).width == 3 * (images.PHONE_W + images.GAP) + images.GAP


def test_keepa_cached_calls_never_wait(monkeypatch):
    from collectors.common import Budget
    monkeypatch.setenv("KEEPA_KEY", "k")
    monkeypatch.setattr(keepa, "cached_json", lambda *a, **k: {"products": []})
    monkeypatch.setattr(keepa, "_state", {"left": 0, "rate": 1, "refill_in_ms": 60_000, "waited_s": 0.0})
    monkeypatch.setattr(keepa, "_sleep", lambda s: (_ for _ in ()).throw(AssertionError("waited on a cache hit")))
    keepa.fetch_products(["B01"], "uk", Budget())
