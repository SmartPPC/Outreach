# Outreach skill handover (formerly "amazon-audit")

This file hands over the **outreach** skill: an outside-in Amazon audit of a prospect brand (built for Amazon UK, also
works for US) that produces a 4-point outreach email, a one-page visual audit (HTML, published as a link) and an A4
PDF. It was built for Smart PPC's prospecting.

- Repository: `SmartPPC/Outreach` (branch `main`, identical to `claude/sweet-ride-9xf549`), commit `0c9ea8e`.
- Skill folder: `.claude/skills/outreach/`. Python pipeline: `run_audit.py`, `collectors/`, `analyse/`.
- Generated on 2026-11-13. Every file in Part 6 and Part 7 is copied verbatim from that commit; nothing is summarised.
- Not included: `analyse/internal_audit.py` and `analyse/internal_report.py` (they belong to the separate
  `internal-audit` skill), `runs/` (temporary run folders and the API cache), API keys.

## Contents
1. What the skill does and what it needs
2. Data sources, endpoints and credentials
3. Workflow: from a brand name to the finished PDF
4. How the HTML and PDF are produced, and where outputs go
5. Rules, thresholds and tone
6. Every file in the skill and its pipeline (verbatim)
7. Worked example: `audits/ultradex-uk-2026-10-21/` (verbatim)

---

## 1. What the skill does and what it needs

**Input:** an Amazon brand store URL, product URL, ASIN, seller URL or brand name; optionally a job advert (text file)
and the brand's website. Marketplace comes from the URL (`amazon.co.uk` → `uk`), or `--marketplace uk`.

**Output** (in `runs/<brand>-<mp>-<YYYY-MM-DD>/`, then copied to `audits/<slug>/`):

| File | What it is |
|---|---|
| `dataset.json` | Every number the audit uses (built by `analyse/build_dataset.py`). Source of truth. |
| `findings.json` | The AI's judgement: headline, up to 5 points with evidence, hero actions, AMC hypotheses. |
| `audit.html` | One-page visual audit rendered from `templates/audit.html` (`analyse/render.py`), published as a private link. |
| `evidence.md` | The data behind every claim, for the follow-up call (`analyse/render.py`). |
| `email.md` | The outreach email: 4 numbered points + Smart PPC paragraph + opt-out (from `templates/email.md`). |
| `<Brand>-Amazon-Audit.pdf` | A4 PDF of the audit page (`analyse/pdf.py`, headless Chromium). |
| `contacts.json` | Contacts found on the brand site, Companies House, LinkedIn search links, Apollo (optional). Never shown on the shareable page. |
| `input.json` | How the input was resolved (brand, marketplace, store id, seed ASINs). |
| `README.md` + row in `audits/INDEX.md` | Written by `analyse/archive.py` when the audit is saved. |

Intermediate files in the run folder (not copied to `audits/`): `js_catalog.json`, `keepa_products.json`,
`keywords_by_asin.json`, `keywords.json`, `js_sov.json`, `serps.json`, `catalog.json`, `ads_bids.json`,
`collect_log.json`, `mobile/<ASIN>.png`.

**Runtime:** Python 3.11+, standard library only for the pipeline (`pytest` for tests). Chromium/Chrome for the PDF.
`Pillow` is used only for the optional phone-size image sheets.

---

## 2. Data sources, endpoints and credentials

Any provider without credentials is skipped and logged in `collect_log.json`; the audit gets thinner but still runs.
All responses are cached on disk for 7 days (`runs/.cache/`, `APA_CACHE_TTL`), so re-runs cost nothing.
Per-run spending caps come from the `APA_BUDGET_*` variables (`collectors/common.py`, class `Budget`).

| Source | Endpoint(s) called | Used for | Credentials (names only) |
|---|---|---|---|
| **Keepa** (`collectors/keepa.py`) | `GET https://api.keepa.com/token` (token check); `GET /product` (`stats=180, rating=1, history=1, days=400, videos=1, aplus=1`); `GET /query` (product finder by brand, fallback); `GET /seller` (`storefront=1`, seller's ASINs, fallback) | Listing content of the best-sellers: title, bullets, images with pixel sizes, videos (creator, duration), A+ alt text, price, list price, sellers, Buy Box owner, rating, reviews, sales rank and monthly rank history, stock-out % (90 days), "bought in past month", category path, listed date, variations | `KEEPA_KEY` (key travels in the URL, so it can't be a proxy-injected secret). Plan used: 1 token/minute; the pipeline paces itself (`APA_KEEPA_MAX_WAIT_MIN`, default 45) |
| **Jungle Scout** (`collectors/junglescout.py`) | `POST https://developer.junglescout.com/api/product_database_query` (brand search, every spelling); `GET /sales_estimates_query`; `POST /keywords/keywords_by_asin_query`; `GET /share_of_voice` | Whole-catalogue map with 30-day units and revenue per ASIN (drives the 80/20 best-seller pick); keywords each best-seller ranks for, with search volume, organic rank, sponsored rank, relevancy, CPC; share of voice (brand vs competitors, organic and sponsored) on brand and category terms | `JS_KEY_NAME`, `JS_KEY` (header `Authorization: KEYNAME:KEY`), or a proxy network secret with `APA_PROXY_AUTH=junglescout` |
| **DataForSEO** (`collectors/dataforseo.py`) | `POST https://api.dataforseo.com/v3/merchant/amazon/products/task_post` + `GET .../task_get/advanced/{id}` (live Amazon search results); `POST /dataforseo_labs/amazon/ranked_keywords/live` (keyword fallback when no Jungle Scout); `POST /on_page/content_parsing/live` (fetch the brand's website pages); `POST /serp/google/organic/live/regular` (Google search for contacts and company pages) | Who actually shows on page one for the brand name and category terms (sponsored and organic), lookalikes bidding on the brand; contact and company research | `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` (Basic auth), or a proxy secret with `APA_PROXY_AUTH=dataforseo` |
| **Amazon SP-API** (`collectors/catalog.py`, optional) | Catalog Items API v2022-04-01: `searchCatalogItems` (brand search), `getCatalogItem` (images, bullets) via `sellingpartnerapi-eu.amazon.com` / `-na` | Authoritative brand search and content when configured | `SPAPI_CLIENT_ID`, `SPAPI_CLIENT_SECRET`, `SPAPI_REFRESH_TOKEN` (LWA) |
| **Amazon Ads API** (`collectors/ads_bench.py`, optional) | Sponsored Products 3.0 Bid Recommendations via `advertising-api-eu.amazon.com` / `advertising-api.amazon.com` | CPC benchmark per keyword, using one of your own advertised ASINs as proxy; otherwise Jungle Scout PPC bids are used | `ADS_CLIENT_ID`, `ADS_CLIENT_SECRET`, `ADS_REFRESH_TOKEN`, `ADS_PROFILE_ID_UK`/`_US`, `ADS_BENCH_ASIN_UK`/`_US` |
| **Amazon Marketing Cloud** (`collectors/amc_bench.py`, optional, offline) | AMC reporting API, queries in `amc_queries/*.sql` (new-to-brand, path to purchase, repeat rate, ad-type overlap) run on your own client instances (`amc_instances.json`) | Category benchmarks for the AMC hypotheses. Never the prospect's own data. Not run in the audits so far | Same Ads API credentials; instance list in `amc_instances.json` (see the example file) |
| **Amazon image CDN** (`collectors/images.py`) | `https://m.media-amazon.com/images/I/<id>` | Phone-size image sheets for the legibility check (needs that host allowed; skipped if blocked) | none |
| **Companies House** (`collectors/contacts.py`) | Public pages under `find-and-update.company-information.service.gov.uk` (company search and officers), fetched through DataForSEO content parsing | Exact, active company matches and officer names for the contact research | none |
| **LinkedIn** (`collectors/contacts.py`) | No API: builds people-search URLs only | Links for the user to look up founders / e-commerce / Amazon roles | none |
| **Apollo.io** (`collectors/apollo.py`, optional) | `POST https://api.apollo.io/api/v1/mixed_companies/search`, `/mixed_people/api_search`, `/people/match` | People at the brand, parent company or seller with titles and verified emails. The free plan blocks people search and email reveal; then the free organisation lookup gives a link `https://app.apollo.io/#/people?organizationIds[]=<id>` for manual reveal | `APOLLO_API_KEY` (or proxy secret, header `x-api-key`, `APA_PROXY_AUTH=apollo`) |

Other environment variables: `APA_PROXY_AUTH` (comma list of providers whose credentials a network proxy injects),
`APA_BUDGET_KEEPA` (400), `APA_BUDGET_JS` (60), `APA_BUDGET_D4S` (40), `APA_BUDGET_SPAPI` (60), `APA_BUDGET_ADS` (20),
`APA_BUDGET_APOLLO_SEARCH` (10), `APA_BUDGET_APOLLO_CREDITS` (3), `APA_CACHE_TTL`, `APA_KEEPA_MAX_WAIT_MIN`,
`APA_DEBUG`, `CHROMIUM` (path to a Chrome/Chromium binary for the PDF). Keys go in `.env` (never committed) or the
cloud environment's settings. See `.env.example` in Part 6.

---

## 3. Workflow: from a brand name to the finished PDF

The skill's own step list is in `SKILL.md` (Part 6). This is what happens underneath.

1. **Resolve the input** (`collectors/resolve.py`). Parses store URLs (brand slug, store page id, `lp_asin`), product
   URLs and bare ASINs (single-ASIN scope), seller URLs and brand names. Splits camel-case slugs into a brand name
   but keeps all-caps runs together ("UltraDEX", not "Ultra DEX"). `brand_spellings()` returns every spelling to
   search (e.g. "UltraDEX" and "Ultra DEX"). `--brand` overrides.
2. **Command:** `python run_audit.py "<store URL | product URL | ASIN | brand>" --marketplace uk [--job-ad job.txt]
   [--brand "<exact name>"] [--website brand.co.uk] [--asin-only] [--top-n 12] [--category-terms 12]`.
   Run it in the background; Keepa at 1 token/minute means ~2 minutes per uncached best-seller variant.
3. **Keepa token check**, and if the brand is unknown (ASIN input) read the brand off the seed ASIN.
4. **Catalogue** (Jungle Scout product database, all spellings merged). Rows are kept only when the brand field matches
   (short brands ≤4 characters match as whole words; ≤3 characters the title must start with the brand). The brand
   name is only ever corrected to another spelling of the same brand. Without Jungle Scout: Keepa brand query, Keepa
   seller storefront and SP-API search, then Keepa product data.
5. **Best-sellers: the 80/20 pick** (`analyse/checks.py: select_heroes`). Drop listings that aren't live (no price,
   no sellers, or no sales). Group by parent ASIN (variation family). Family revenue counts repeated or near-identical
   units once, at the lowest price (Jungle Scout repeats a family's sales on every child). Rank families by revenue and
   add them until they cover **80%** of revenue, at most **12** families (`--top-n`). The lead ASIN of each family is
   the child with most units, then reviews; later swapped for the variant Keepa sees with a live offer.
   Single-ASIN mode (`focus_on_asin`) keeps only the given ASIN's family with it as the lead.
6. **Keepa on the best-sellers:** the lead plus up to 2 more variants per family (max 30 ASINs).
7. **Phone image sheets** (`collectors/images.py`) for each lead: stitches the gallery at phone width into
   `mobile/<ASIN>.png` so the annotations' legibility can be judged. Skipped if the image CDN is blocked.
8. **Keywords per best-seller** (Jungle Scout keywords by ASIN; DataForSEO ranked keywords as fallback). Merged into
   `keywords.json`. Brand terms = brand name, brand without spaces, plus the top branded keyword. Category terms = the
   top 12 unbranded keywords.
9. **Share of voice and live search results:** Jungle Scout share of voice for the brand term and category terms;
   DataForSEO Amazon results for the brand terms and the top 8 category terms (who is sponsored above the brand,
   lookalikes on the brand name, brand's first appearance).
10. **CPC benchmark:** Ads API bid recommendations if configured, else Jungle Scout CPCs.
11. **Contacts** (`collectors/contacts.py`): fetches the brand site's home, contact and about pages; extracts emails
    and classifies them (personal, business, role, generic); company name and number; Companies House exact active
    matches and officers; parent company and Buy Box seller name; LinkedIn search links per organisation and role;
    Apollo if configured. Never guesses an email format as fact (suggestions are marked unverified).
12. **Build the dataset** (`analyse/build_dataset.py: build`) into `dataset.json`:
    - `focus` (catalogue size, live ASINs, hero families, revenue share, estimated monthly revenue) and `heroes`
      (per best-seller: revenue, units, price, rating, reviews, category, sellers, Buy Box owner, sold by Amazon,
      sales rank and history, stock flag, category mismatch, mixed family, seller and price flags, listing rubric,
      mobile check, keywords with organic/sponsored ranks, wasted terms, push terms).
    - `quick_wins`: **duplicate listings** and **catalogue clutter** (below), mixed variation families.
    - `asin_map`, `catalogue` (launches by quarter, categories), `content`, `competitors` (share of voice, who
      bids on the brand), `ads_observed`, `strategy` (keyword map and indicative budget), `amc_benchmark`.
13. **Keyword map: PUSH, CUT and the other statuses** (`_tier`, `_status`, `_strategy`; constants
    `TOP_OF_PAGE=4`, `PAGE_ONE=20`, `PAGE_TWO=60`):
    - Tier: `brand` (contains the brand), `competitor` (contains a rival's name), `long_tail` (4+ words or volume
      < 500), `core` (organic rank ≤ 20 or relevancy in the top quarter), else `category`.
    - Status from organic and sponsored rank:
      - organic ≤ 4 with an ad → `own`; organic ≤ 4 without → `organic_top_unprotected`
      - organic 5–60 without an ad → **`push`** ("Ranks page 1–2, no ads: push to top"); with an ad → `sponsored_support`
      - not ranked but sponsored → `sponsored_only`; neither → `missing`
      - brand term that a rival bids on, where the brand is unprotected or missing → `brand_defence_gap`
    - Priority weight: push 1.0, brand defence gap 1.0, missing 0.6, organic_top_unprotected 0.5,
      sponsored_only 0.4, sponsored_support 0.3, own 0.1. Indicative budget = searches × clicks per search
      (8/12/20%) × CPC × target sponsored share by tier (brand 50%, core 20%, category 10%, long-tail 15%,
      competitor 5%).
    - **CUT (wasted terms)** (`checks.wasted_terms`): only terms the product is sponsored on. Own-brand terms are never
      waste. If organic rank > 50 and the search has a qualifier that makes it a different product (not a generic
      modifier, not in the title, not a word from searches it already ranks top-20 for) → "different product
      ("<word>")", or "competitor's brand: worth reviewing" if the word is a rival's name. If organic rank > 100 and the
      term is a partial brand term or unrelated to the title → "partial brand term" / "unrelated to the product".
14. **Mobile score** (`analyse/mobile.py`, rubric in `references/mobile-rubric.md`), per best-seller, 0–100
    (good = 2 points, warn = 1, fail = 0, averaged over the checks that have data):
    - Zoom: every image ≥ 1000 px on the longest side (below that Amazon disables zoom); warn under 1600 px.
    - Image count: ≥ 7 good, 5–6 warn, < 5 fail.
    - Video: none = fail; only influencer/customer videos = warn; brand video > 90 s = warn; missing length = good.
    - Title on mobile: brand, product type and size must sit in the first 80 characters.
    - Bullets: flag bullets over 250 characters.
    - A+ on a phone: flag A+ images whose alt text carries more than 30 words of copy.
15. **Listing rubric** (`analyse/rubric.py`, `references/scoring-rubric.md`): images, video, A+, title length, bullet
    count and length, rating and reviews, banded good / warn / fail.
16. **Duplicate listings** (`checks.duplicates`): live listings under different parents whose title words (minus the
    brand and sizes) overlap ≥ 80% (Jaccard). **Clutter** (`checks.clutter`): title is only the brand name, title not
    in the marketplace language (2+ foreign words), brand missing from the title, brand spelled inconsistently.
17. **Seller, price and stock flags** (`checks.py`): a seller holding the Buy Box on ≥ 80% of the range (or 3× the
    runner-up) is the brand's own account, not a reseller. If Amazon holds the Buy Box (1P/Vendor) price and reseller
    points are suppressed. Crowded listing = 5+ sellers. Stock flag only when out of stock 10–60% of the last 90 days
    and listed over 180 days (above 60% reads as discontinued; new or seasonal listings are skipped). Category mismatch
    = the title's product type doesn't match the category leaf.
18. **The AI's part** (SKILL.md steps 3–8): reads `dataset.json` against `references/insight-playbook.md`,
    `ad-strategy-framework.md`, `amc-playbook.md` and (with a job ad) `job-ad-mapping.md`; picks up to 5 points about
    the best-sellers, each with evidence from the dataset; writes `findings.json`; renders and publishes the page;
    writes the 4-point `email.md`; picks who to send it to.
19. **Render, PDF, save:** `python -m analyse.render runs/<slug>` → `audit.html` + `evidence.md`;
    `python -m analyse.pdf runs/<slug>` → PDF; `python -m analyse.archive runs/<slug> --link <published URL>` →
    `audits/<slug>/` + README + `audits/INDEX.md` row; then commit and push.

---

## 4. How the HTML and PDF are produced, and where outputs go

- **HTML:** `analyse/render.py` reads `dataset.json` and `findings.json` and fills the slots in
  `.claude/skills/outreach/templates/audit.html` (sections: headline and snapshot tiles, the points, best-seller cards
  with Fix / Push / Cut / Mobile, content, keyword map and budget, competitors, AMC). Charts are inline SVG with a
  table beside each. Single-ASIN runs change the titles ("<Brand> <ASIN> <MP> Audit"). The page is self-contained (no
  external scripts) and is published as a private web page; the link goes into `audits/<slug>/README.md`.
- **PDF:** `analyse/pdf.py` wraps `audit.html` in a print page (A4, light theme forced, collapsed sections opened,
  cards and table rows kept whole across pages) and prints it with headless Chromium:
  `chrome --headless=new --no-sandbox --disable-gpu --no-pdf-header-footer --virtual-time-budget=5000
  --print-to-pdf=<out> file://<wrapper>`. Chromium is found via `CHROMIUM` or `/opt/pw-browsers/chromium-*/chrome-linux/chrome`.
  File name: `<Brand>-Amazon-Audit.pdf`, or `<Brand>-<ASIN>-<MP>-Amazon-Audit.pdf` for single-ASIN audits.
- **Where outputs go:** the run writes to `runs/<brand>-<mp>-<YYYY-MM-DD>/` (temporary, git-ignored, dated, so a
  next-day rerun makes a new folder). `analyse/archive.py` copies the deliverables (`email.md`, `audit.html`,
  `findings.json`, `evidence.md`, `dataset.json`, `input.json`, `job_ad.txt`, `contacts.json`, the PDF) to
  `audits/<slug>/`, writes `README.md` there and adds a row to `audits/INDEX.md`.
- **Worked example:** `audits/ultradex-uk-2026-10-21/` (Part 7) from
  `python run_audit.py "https://www.amazon.co.uk/stores/UltraDEX/page/02885511-9448-4D57-A25F-B3812F09FE2C?lp_asin=B071Z1B158" --brand UltraDEX`:
  84 ASINs found, 45 live, 6 best-seller families making 85% of ~£99,890 a month.

---

## 5. Rules, thresholds and tone

The binding rules are in `SKILL.md` ("Ground rules", "Smooth runs", steps 4–10) and the references in Part 6. The ones
that matter most:

- **Best-sellers first.** Every point is about the families making ~80% of revenue and says what to do with them.
  Never raise listings that aren't live, sell little, or have been out of stock a long time (usually discontinued).
- **Quick wins are one point at most** (duplicates, clutter, mixed families, wrong categories on best-sellers).
- **Outside-in only.** We haven't seen their accounts: spend, revenue and budget are estimates and are worded that way
  ("we estimate", "roughly", "looks like"). Never claim to have looked at a live listing.
- **Every point needs evidence from `dataset.json`.** No number that isn't in the dataset. Empty sections are left out.
- **AMC figures are category benchmarks from other accounts**, phrased as hypotheses, never the prospect's numbers.
  Never name clients or reveal a client's numbers.
- **Amazon holds the Buy Box (1P/Vendor):** never pitch pricing or reseller points.
- **Don't pitch ads to "defend" a #1 ranking** unless a competitor ad sits above it; point budget at big searches where
  it ranks #2–10. A Jungle Scout sponsored "–" means "not seen near the top", not "no ads".
- **Two marketplaces:** compare category and conversion between them.
- **Contacts:** never guess an email address; Companies House matches must be exact and active; flag a conflict if the
  brand belongs to the user's own employer and don't draft outreach.
- **Thresholds:** 80% revenue share, max 12 families, top of page ≤ 4, page one ≤ 20, page two ≤ 60, wasted-term
  organic cut-offs 50 and 100, duplicate similarity 0.8, crowded = 5 sellers, stock flag 10–60% out of stock over 90
  days and only for listings over 180 days old, brand seller ≥ 80% of Buy Boxes, mobile: zoom 1000/1600 px, 7 images,
  video ≤ 90 s, 80-character mobile title, 250-character bullets, 30 words of A+ image text.
- **Tone:** a senior consultant writing to a busy brand owner. Plain English, short sentences, specific numbers, no
  jargon or acronyms in the email, no hype. The email is exactly 4 numbered points, a short Smart PPC paragraph
  (1 freelance slot, £950 a month covering stock, content, ads and new product development, no fixed contracts), an
  offer of the detailed report free of charge, no links or attachments, and an opt-out line. Template:
  `templates/email.md`.

---

## 6. Every file in the skill and its pipeline (verbatim)

## 6.1 Skill files (`.claude/skills/outreach/`)

### `.claude/skills/outreach/SKILL.md`

````markdown
---
name: outreach
description: Smart PPC outreach audit. Audit a prospect's Amazon business from the outside (no account access) and draft a consultant outreach email with 4 points, plus a one-page visual audit and PDF in Smart PPC style. Use when the user pastes an Amazon brand store URL, seller URL, product URL, ASIN or brand name and wants a prospect audit, outreach email, or "what would we fix" summary, optionally alongside a job advert. For a client's own Seller Central or Amazon Ads exports, use the internal-audit skill instead.
---

# Outreach audit (Smart PPC prospects)

Turns a brand, store URL or ASIN (plus an optional job advert) into:
- `runs/<slug>/email.md`: a brief outreach email with 4 plain-English points, offering the detailed report free of charge
- `runs/<slug>/audit.html`: a one-page visual audit, published as a private artifact link
- `runs/<slug>/evidence.md`: the data behind every claim, for the follow-up call

The Python collectors handle data and arithmetic, and their numbers are the source of truth. Your job is judgement and writing: decide what matters, connect it to what the prospect is asking for, and say it the way a senior consultant would.

## Ground rules
- **Best-sellers first.** `dataset.focus` and `dataset.heroes` hold the product families making ~80% of
  revenue. Every point is about one or more of them, and says what to do with it. Never raise an ASIN
  that isn't live, has tiny sales, or has been out of stock for a long stretch. Those are usually
  discontinued lines and only make the email look untargeted.
- **Quick wins are one point at most.** `dataset.quick_wins` (duplicates, untidy titles, mixed variation
  families) and wrong categories on the best-sellers can be grouped into a single "tidy-up" point.
- **Always deliver all three outputs:** the email, the published audit page, and `evidence.md`. Don't end
  with a chat summary and an offer to make a page.
- **Outside-in only.** We have not seen their Seller Central or ad account. Never write as if we have. Spend, revenue and budget figures are estimates and must be labelled that way: "we estimate", "roughly", "looks like".
- **Every point needs evidence from `dataset.json`.** If a number isn't in the dataset, don't use it. If a section is empty because a provider was skipped, leave it out. Don't fill gaps with guesses.
- **AMC numbers are category benchmarks from other accounts, never this prospect's.** Phrase them as hypotheses ("in your category, typically…"). If the benchmark says `low_sample: true` or isn't available, describe what AMC would show without quoting figures.
- **Never name our clients** or reveal any single client's numbers.

## Smooth runs: lessons from real audits
**Running the pipeline**
- **Run `run_audit.py` in the background** and wait for the completion notification. Don't poll.
  Keepa is on 1 token a minute, so a run waits about 2 minutes per uncached best-seller variant.
- **One audit at a time.** Parallel runs share Keepa's token bucket, push it negative and slow both.
- **Reruns are free.** Responses are cached for 7 days and cached Keepa calls never wait. After fixing
  something, rerun the same command rather than hand-pulling data.
- **Stopping a run:** use the task-stop tool, never `pkill -f run_audit`, which also kills the shell running it.
- **Run folders are dated** (`runs/<brand>-<mp>-<YYYY-MM-DD>/`). A rerun the next day writes a new folder,
  so read the folder the run printed, not an older one.

**Checking the data before writing**
- **Brand name.** The catalogue search tries every spelling of the brand ("UltraDEX" and "Ultra DEX",
  "SuperFacialist" and "Super Facialist") and merges the results. The searched spellings are listed in
  `collect_log.json`. The brand comes from the store URL slug. If `js.catalog` returns very few ASINs, or
  `focus.live` is 0, the spelling is probably off (e.g. "UltraDEX" read as "Ultra DEX"). Rerun with
  `--brand "<exact name on Amazon>"`.
- **Short brand names** (2–4 characters, e.g. "W7") match only as whole words, and the brand is never
  renamed to a different brand found in the results. If `prospect.brand` doesn't match the seed product's
  brand, rerun with `--brand`.
- **Marketplaces differ.** The same ASIN can sit in a different category, or have different content, on
  .co.uk and .com. Compare the two when auditing both, because a mismatch is often a finding.
- **Revenue.** Jungle Scout repeats a family's sales on every variant; the pipeline counts it once. If one
  family still looks implausibly large next to the brand total, check its variants' `units_30d`.
- **Lead variant.** Each best-seller is represented by the variant Keepa sees with a live offer. If a hero
  shows no price, rating or bullets, its Keepa record is thin. Don't report "0 bullets" or "no reviews"
  from it; say "not captured".
- **Seller names.** A seller that holds the Buy Box on 80%+ of the range is the brand's own account,
  not a reseller.
- **Amazon holds the Buy Box (Vendor/1P).** Amazon sets the retail price, so a deep discount or many other
  sellers isn't the brand's problem to fix. Never pitch it. Price and reseller points only apply when a third
  party holds the Buy Box.
- **Company matches.** Companies House matches must be exact and active. Treat a dissolved company with the
  same name as a different business.
- **Conflicts.** Check `contacts.company` against the user's own employer. If the brand belongs to the
  company the user works for, flag it and don't draft outreach.
- **Amazon itself is blocked** in cloud sessions. Never claim to have looked at a live listing. Verify
- **Don't pitch ads to "defend" a #1 ranking.** If the listing is already #1 organically and nothing sits above
  it, spend there buys little. Only suggest brand or #1 defence when a competitor ad is shown above the listing.
  Point budget at big searches where it ranks #2–10 instead.
- **A Jungle Scout sponsored "–" means "not seen near the top", not "no ads".** Accounts we later saw had
  heavy spend on those searches. Write "ads not showing near the top" rather than "no ads".
- **Two marketplaces:** compare category and, where known, conversion between them. The same product in the
  right category in one market is the strongest evidence for a category fix in the other.
  claims against Keepa, Jungle Scout or DataForSEO data instead.

**Contacts**
- **The Apollo free plan** blocks people search and email reveal, through both the API and the connector.
  The free `apollo_organizations_lookup` still works: use it to get the Apollo company ID, then give the user
  `https://app.apollo.io/#/people?organizationIds[]=<id>` so they can reveal the email in the app (1 credit).
- **When a named person is found** (e.g. from LinkedIn), add them to `contacts.json` and the audit README,
  and personalise the email ("Hi <first name>"). Never guess an address format; bounces hurt deliverability.
- **Send outreach from the Smart PPC email address** (info@smartppc.ai) rather than LinkedIn. LinkedIn
  messages always show the user's personal profile.

## Steps

### 1. Gather inputs
Get the prospect identifier from the user. If they gave a job advert:
- **Pasted text:** save it to a file.
- **URL:** fetch the page and save the advert text to a file.

Pass that file with `--job-ad`. If the marketplace isn't obvious from the URL, ask whether it's UK or US.

**Single-product audits.** When the user gives one bare ASIN, or a product link with no store page, the tool
runs in single-product mode (`scope: "asin"`; force it with `--asin-only`). Only that product's variation family
is analysed, with the given ASIN as the lead, and brand totals are kept for context only. A bare ASIN has no
marketplace, so ask or use the user's usual one (`--marketplace uk`). All 4 email points must be about this
product. Brand-wide issues, such as a competitor bidding on the brand name, only count if they hit this product
directly. The email opens with "I took a quick look at your <product> on Amazon UK…".

### 2. Collect
Always run the pipeline. Don't hand-pull data, except to fill a step that failed in `collect_log.json`. If you
do fill a gap by hand, say so in `evidence.md`.
```bash
python run_audit.py "<input>" [--marketplace uk|us] [--job-ad /path/job.txt] [--website https://brand.com]
```
This prints the run directory. Check `collect_log.json` in it:
- If Keepa was skipped there is no ASIN map. Stop and tell the user which key is missing.
- Other skipped providers just make the audit thinner. Mention them in your reply.

Keepa is the slow part. On a 1 token/minute plan it only fetches the best-sellers, and the script
waits for tokens as needed (expect ~1–2 minutes per best-seller after the first ~30). Run it in the
background and keep going with the other steps.

Cost controls: `--top-n` (max best-seller families, default 12), `APA_KEEPA_MAX_WAIT_MIN` (default 45), and the `APA_BUDGET_*` environment variables. Reruns on the same day hit the cache and cost nothing.

If a connected MCP server covers a provider whose API key is missing (Jungle Scout, Amazon Ads or Keepa), you may use it to fill that gap by hand. Record what you pulled in `evidence.md`.

### 3. Analyse
Read `dataset.json`, then `job_ad.txt` if present, and these references:
- `references/scoring-rubric.md`: what the content checks mean and when they matter
- `references/mobile-rubric.md`: the mobile checks, plus how to review the phone-width image sheets
- `references/ad-strategy-framework.md`: keyword tiers, visibility logic, budget
- `references/amc-playbook.md`: AMC hypotheses and week-one questions
- `references/insight-playbook.md`: finding → recommendation → phrasing
- `references/job-ad-mapping.md`: only when there's a job ad

Amazon itself is blocked from cloud sessions, so check claims against the collected data instead. For
example, a wrong-category flag should be confirmed by comparing the title with
`heroes[].category`. Hedge anything that only one source supports.

### 4. Pick up to 5 points
Work through `heroes` in revenue order. For each best-seller, the biggest lever is usually one of:
- **Fix:** wrong category, mixed variation family, reseller on the Buy Box, a best-seller that keeps
  running out, deep discounting.
- **Push:** `targets`, i.e. page-1/2 terms with no ad support, and brand-term defence.
- **Cut:** `wasted_terms`, i.e. sponsored on unrelated or partial-brand terms (auto/broad drift).
- **Content:** the `content` checks.
- **Mobile:** the `mobile` checks and the phone-width image review (see mobile-rubric.md).

Then score each candidate from 1 to 3 on three things:
- **Impact:** revenue at stake, using `family_revenue_30d`.
- **Confidence:** directly observed beats estimated.
- **Fixable by us:** PPC, listings and AMC are our core. Supply chain or pricing is not.

Multiply the three scores. Matching what the job ad asks for adds one extra point to impact.

Keep the top 5, ordered by revenue at stake. Every point names a best-seller, except for at most one tidy-up point and at most one AMC point. Fewer, stronger points beat five weak ones.

### 5. Write `findings.json`
```json
{
  "headline": "One sentence: the single biggest opportunity, specific to them.",
  "points": [
    {
      "category": "advertising | content | catalogue | competitors | amc",
      "title": "Product + action, e.g. 'Cleansing Balm: move it to Cleansing Balms and push \"cleansing balm\"'",
      "detail": "2 sentences max: what we saw on that best-seller (with a number), and what we'd do first.",
      "evidence": ["Specific data points with numbers and sources from dataset.json"],
      "job_ad_quote": "Exact phrase from the job ad this answers, or null"
    }
  ],
  "mobile_review": {"<hero ASIN>": {"legible": true, "worst_image": "PT03", "verdict": "One line on how it reads on a phone"}},
  "hero_actions": {"<hero ASIN>": "One line: the single most valuable action for this best-seller"},
  "content_note": "1-2 sentences summarising the content table.",
  "ad_strategy_summary": "2-3 sentences: which tiers to fund, why, indicative budget.",
  "amc_hypotheses": ["2-4 benchmark-based expectations, phrased as hypotheses"],
  "amc_questions": ["3-5 questions AMC would answer in week one"]
}
```

### 6. Render and publish
```bash
python -m analyse.render runs/<slug>
```
The audit page is the "detailed report" the email offers. It's held back for the follow-up, never
linked or attached in the first email. Publish `runs/<slug>/audit.html` as a private Artifact if the Artifact tool is available:
- icon `chart`
- description "Outside-in Amazon audit for <brand>"

Otherwise give the user the file path.

Also make the PDF version, which is the attachment for when a prospect replies asking for the report:
```bash
python -m analyse.pdf runs/<slug>
```

### 7. Write `email.md`
Follow `templates/email.md` exactly:
- **Subject:** the single most surprising finding.
- **Opening:** one line that's generous about what's working.
- **Exactly 4 numbered points,** taken from the top of `findings.json`. Each is a bold one-sentence headline plus one plain-English sentence, with a single number where it helps.
- **About Smart PPC:** the fixed paragraph from the template: what Smart PPC is, 1 freelance slot, full account management (stock, content, ads, NPD strategy) at £950/month, no fixed contracts.
- **Close:** offer the detailed report free of charge.

Don't include a link or an attachment, and leave out jargon (no "SP", "ACoS", "exact match", "variation family"). If there's a job ad, echo its wording in the opening line.

### 8. Pick who to send it to
Read `contacts.json`. The research step covers every company behind the brand: the brand itself, the
company named on its website (e.g. "operated by HBL Ventures LLC") and its Amazon seller account. It holds:
- **`emails`:** addresses published on the brand's site or found by web search, each tagged personal,
  business, role or generic, with its source.
- **`apollo.people`:** when `APOLLO_API_KEY` is set, people currently in founder, ecommerce, Amazon or
  marketing roles at any of those companies, with LinkedIn profiles. The top 3 have a verified work email.
- **`companies_house`:** exact-name, active UK companies and the people listed on them. Dissolved
  namesakes are ignored.
- **`linkedin_searches`:** one-click LinkedIn people searches per company, for the user to open while logged in.

**If the Apollo.io connector is enabled in this session** (tools named like `apollo_search_people`,
`apollo_search_organizations` and `apollo_enrich_person`), use it when `contacts.json` has no `apollo` section:
1. For each name in `contacts.organisations`, plus the brand's domain, run `apollo_search_organizations` and
   keep exact name or domain matches only.
2. Run `apollo_search_people` on those organisations with titles founder, owner, CEO, ecommerce, Amazon,
   marketplace and marketing. Rank them in that order and only keep people whose *current* employer is one of
   the matched organisations.
3. Run `apollo_enrich_person` on the top 3 at most (each uses an Apollo credit) to get verified work emails.
4. Add the results to `contacts.json` under `apollo.people` (name, title, organisation, linkedin, email,
   email_status), then save the audit as usual.

Who to pick:
- **To:** a verified Apollo email for the best-ranked person (founder or owner, then ecommerce or Amazon,
  then marketing), or a named person's published address. Otherwise a business inbox (`wholesale@`, `trade@`,
  `partnerships@`, `marketing@`). Only fall back to `hello@`/`info@` when nothing better exists, and never
  use complaints@, legal@, privacy@ or vip@.
- **Suggested addresses** only exist when a published personal address revealed the format. Pass them on
  with "unverified, check before sending". Never make up an address yourself.
- **If `only_generic` is true:** tell the user, and give them the LinkedIn search links for each company name.
- **Never** recommend someone whose Apollo title or employer doesn't match one of the brand's companies.
- **Never** put contact details in `findings.json` or the audit page, because it gets shared with the prospect.

### 9. Save the audit
`runs/` is temporary and isn't committed, so save every finished audit into the repo:
```bash
python -m analyse.archive runs/<slug> --link <published audit page URL>
git add audits && git commit -m "Audit: <Brand> (<uk|us>)" && git push -u origin <current branch>
```
This copies the email, audit page, findings and evidence into `audits/<slug>/`, writes a README for the folder and adds a row to `audits/INDEX.md`.

### 10. Reply to the user
Include:
- the email text, ready to paste
- the audit link, noting it's for the follow-up and is private until shared
- who to send it to: the recommended To address and its source page, any names found, and whether a
  LinkedIn lookup is needed
- where it's saved (`audits/<slug>/`)
- one line listing any data gaps, e.g. "no Jungle Scout key, so keyword and sales sections are thin"
````

### `.claude/skills/outreach/references/ad-strategy-framework.md`

```markdown
# Advertising strategy framework

## Keyword tiers (`strategy.keyword_map[].tier`)
| Tier | Definition | Default play |
|---|---|---|
| Brand | contains their brand name | Defend: SP exact + SB headline at top of search. Cheap clicks, high CVR |
| Core | ranks page 1 organically, or top-quartile relevancy | Win the top of page: SP exact + SB Video |
| Category | generic, high volume, lower relevancy | Grow share: SP phrase/broad + SB, tight bids |
| Long-tail | 4+ words or < 500 searches/mo | Efficient conversions: SP exact/phrase harvesting |
| Competitor | contains a rival brand | Conquest selectively: SP product targeting + SD, small budget |

## Visibility status (`status`)
- `push`: ranks organically on positions 5–60 but isn't sponsored. **The best visibility lever.**
  Ads take them to the top of page while organic rank catches up. Lead with these.
- `brand_defence_gap`: a competitor bids on their brand term and they don't. This is easy to explain and
  quick to fix, and it usually makes a strong opening email point.
- `organic_top_unprotected`: ranks top 4 organically with no ad cover, so a competitor ad can sit above them.
- `missing`: a relevant term where they don't appear at all. Pitch it as new reach, a longer-term play.
- `sponsored_only`: they pay for visibility on a term where their organic rank is weak. This may be inefficient spend.
- `own` / `sponsored_support`: healthy. Mention these only to show balance.

## Focus on visibility
The recommendation is to put spend where it buys **position on terms that matter**, not to spread
budget thinly. Order of funding:
1. Brand defence gaps
2. `push` terms in the core tier
3. `push` terms in the category tier
4. Missing core terms
5. Remarketing and retention through SD

## Budget (`strategy.budget`)
For each focus keyword: search volume × clicks per search × target sponsored share of voice for its
tier × CPC. The constants are in `analyse/build_dataset.py`, and the assumptions are printed on the
audit page.
- Quote it as "an indicative £X–£Y per month to own these terms". Use ±25% around `monthly_total`.
- Never present it as their current spend or as a guaranteed return.
- `ads_observed.est_monthly_spend_on_sampled_terms` is a rough read of what they spend today on the
  sampled terms. Use it only to say "it looks like spend is concentrated in…" or "light".

## Talking points that land
- "X of your top 10 keywords show no sponsored placement for you."
- "Brand Y appears in the sponsored slot above your listing when people search your brand name."
- "You rank #12 organically for '<term>' (N searches/mo). That's page one but below the fold.
  A targeted SP exact campaign would put you at the top while organic rank catches up."
```

### `.claude/skills/outreach/references/amc-playbook.md`

```markdown
# AMC playbook

AMC data exists only inside an advertiser's own instance. Before access we use:
1. `dataset.amc_benchmark`: anonymised medians across our managed accounts in the prospect's
   main category, built by `collectors/amc_bench.py`.
2. `strategy.repeat_signals`: public signs of repeat buying, namely Subscribe & Save coverage,
   multipacks, and whether the category is consumable.

## Writing hypotheses
- Benchmarks available (not `low_sample`): "In <category>, buyers typically see ~<avg touches> ad
  touches before their first purchase, and <share_3plus>% see three or more. Without SB or SD
  visible, much of that path is likely going to competitors."
- `low_sample: true` or no benchmark: describe the mechanism without numbers. For example: "AMC would
  show how many touches your buyers need and which ad types start the journey."
- Repeat likelihood high: "In consumable categories we typically see a meaningful share of buyers
  reorder within ~<avg_days_to_repeat> days. An SD remarketing audience built from past purchasers
  usually converts well above prospecting."
- `multi_ad_type_cvr_lift` > 1.3: "Shoppers who see SP plus SB or SD convert ~<lift>× more often than
  SP-only shoppers in this category. If they only run SP, that's the case for a broader mix."

## Week-one AMC questions (pick 3–5 that fit)
- How many ad touches, and which ad types, come before a first purchase?
- What share of ad-attributed sales are new-to-brand, by campaign type?
- What's the repurchase rate and the typical gap between orders? Is it worth building a retention audience?
- Which upper-funnel touches (SB Video, SD, DSP) are followed by branded searches?
- Which ASIN do customers buy first, and what do they buy next? This tells us where to spend on acquisition.
- How much do audiences overlap across SP, SB and SD? Are we paying twice for the same shoppers?

## Never
- Present a benchmark as their number.
- Mention which clients the benchmark came from, or give a single client's figure.
```

### `.claude/skills/outreach/references/insight-playbook.md`

```markdown
# Insight playbook: from finding to phrasing

| Dataset signal | Recommendation | Email phrasing (adapt) |
|---|---|---|
| `heroes[].flags` wrong_category | Move to the right category, which affects rank and relevance | "Your <product> (~£X/mo) is listed under <category>, so it ranks #<n> among <wrong items> instead of competing in <right category>." |
| `heroes[].flags` mixed_variation_family | Split the family by product type | "Your balm, scrub and night cream share one variation family, which confuses search and the category." |
| `heroes[].wasted_terms` | Negatives on unrelated and partial-brand terms; move budget to `targets` | "<Product> is showing ads on '<term>' and '<term>', which have nothing to do with it. That budget would work harder on '<target>'." |
| `heroes[].targets` push | Exact-match SP at top of search | "<Product> already ranks #<n> for '<term>' (<vol>/mo) with no ad support. That's the quickest visibility win." |
| `heroes[].flags` sellers (Buy Box held by a reseller, crowded listing, above list price; only raised when a third party holds the Buy Box, never when Amazon sells it) | Brand Registry and distribution controls | "A reseller holds the Buy Box on <product>, so you don't control its price or the ad spend's return." |
| `heroes[].flags` stock (10–60% out of stock) | Inventory planning on the best-seller | "<Product> was out of stock ~<x>% of the last 90 days. That's lost sales and lost rank on your best-seller." |
| `heroes[].mobile` video warn (influencer-only) | Add a short brand video | "Your best-seller has 7 videos, but all from influencers. A 30-second brand video would explain it faster on a phone." |
| `heroes[].mobile` A+ fail (text-heavy) | Rebuild A+ for mobile | "Half your A+ images carry paragraphs of text that shrink to unreadable on a phone." |
| `heroes[].mobile` zoom fail | Re-upload images at 2000px | "Some of your images can't be zoomed, so shoppers can't check the details." |
| `quick_wins.duplicates` / `clutter` | Merge duplicates, fix titles (group into one point) | "<n> products are listed twice, which splits reviews and rank, and a few titles are missing the brand name." |
| `competitors.brand_term_attackers` non-empty, `prospect_sponsored_on_own_brand` false | Launch brand defence SP + SB | "<Rival> is buying the top ad slot when shoppers search '<brand>', and you're not there to block it." |
| Several `push` focus keywords | Top-of-search SP exact on page-1 terms | "You already rank on page one for '<term>' (<vol> searches/mo) but sit below the fold, so a small exact-match campaign moves you to the top." |
| `ads_observed.sponsored_coverage` < 0.3 | Expand coverage of top terms | "We only saw you advertising on <n> of your top 30 keywords." |
| `content.summary.share_no_video` ≥ 0.5 | Video on hero ASINs + SB Video | "<x> of your top <n> listings have no video, which also rules out Sponsored Brands Video." |
| `share_no_aplus` ≥ 0.3 | A+ rollout | "<x> best-sellers are missing A+ content, so that's free conversion lift." |
| `share_under_7_images` ≥ 0.5 | Image stack (infographics, lifestyle, scale) | "Most listings use <n> of the 7+ image slots." |
| `variation_consolidation` non-empty | Merge into variation families | "<n> separate listings look like one product in different sizes. Combining them pools reviews and rank." |
| Hero ASIN rating < 4.0 | Fix before scaling | "Your top seller is at <r>★. We'd fix the review drivers before pushing more traffic to it." |
| `catalogue.revenue_yoy_pct_last_3m` < 0 or BSR worsening | Recover share | "Rank on your top sellers has slipped ~<x>% year on year while <rival> has grown." |
| `top3_revenue_share` > 0.6 | De-risk concentration | "Three ASINs drive roughly <x>% of sales, so growing the rest of the range lowers the risk." |
| `competitors.sov_change_vs_last_run` shows a rival rising | Respond to a specific rival | "<Rival> has taken ~<x> points of share on your core terms since <date>." |
| `positioning_page1` price well above competitors with a lower rating | Value story in content | "You're priced ~<x>% above the page-one median with a lower rating, so the listing needs to justify the premium." |
| `repeat_signals.likelihood` high, no SD visible | Retention / remarketing | "Your category is built on repeat orders. AMC would show how many of your buyers come back, and we'd build audiences around that." |

Tone: specific, generous, confident. Show we did the homework. Each point should feel like a free
insight they could act on, while making it clear that doing it well takes an expert.

Never use: ASINs that aren't live, long-out-of-stock or discontinued lines, low-sales products, or the
total ASIN count as a criticism. Those read as untargeted.
```

### `.claude/skills/outreach/references/job-ad-mapping.md`

```markdown
# Job advert → findings

Read the advert for: the responsibilities, the KPIs they mention, the channels, the markets, and
any named pain points ("inconsistent ACoS", "scale internationally"). Quote their words back in
`job_ad_quote` and in the email.

| They ask for | Look in dataset | Lead with |
|---|---|---|
| "Grow sales / scale revenue / hit targets" | `strategy.focus_keywords` (`push`), `catalogue.revenue_*` | Visibility gaps on page-1 terms + indicative budget |
| "Manage / optimise PPC", "improve ACoS / ROAS / TACoS" | `ads_observed`, `sponsored_only` keywords, tiers | Spend focus: fund push and brand terms, cut sponsored-only terms (no ACoS claims; we can't see it) |
| "Brand protection / defend brand" | `brand_term_attackers` | Brand defence |
| "Launch new products / NPD" | `launches_by_quarter`, content on newest ASINs | Launch playbook + content gaps on new ASINs |
| "Listing optimisation / content / creative" | `content` | The specific missing images, video and A+ |
| "Market share / competitor analysis" | `competitors.share_of_voice`, `sov_change` | Who is winning which terms |
| "DSP / full-funnel / AMC / data-driven" | `amc_benchmark`, `repeat_signals` | AMC path-to-purchase and retention hypotheses |
| "Expand to US / UK / EU" | rerun with the other `--marketplace` | Compare coverage across marketplaces |
| "Retention / LTV / subscriptions" | `repeat_signals`, AMC repeat metrics | S&S + SD remarketing |

When the ad lists many things, pick the two or three that the data supports most strongly. Don't
try to hit every bullet. If the ad is for an in-house hire, position us as a faster or lower-risk
alternative, or as support alongside the hire. Mention that in the email hook, not in the audit page.
```

### `.claude/skills/outreach/references/mobile-rubric.md`

```markdown
# Mobile rubric

Most Amazon shopping happens on the app or mobile web. On a phone:
- search results show a small thumbnail and roughly the first 80 characters of the title
- the gallery is swiped full-width at about 375px
- bullets sit collapsed under "About this item"
- A+ modules stack full-width, so text baked into images shrinks

`analyse/mobile.py` scores every best-seller. Keep the thresholds here and in the code in step.

| Check | Good | Warn | Fail | Why it matters on mobile |
|---|---|---|---|---|
| Zoom | all images ≥1600px | 1000–1599px | any <1000px (zoom disabled) | Shoppers pinch to inspect texture, ingredients and size |
| Images | 7+ | 5–6 | <5 | Swiping the gallery is the main way people explore a product on mobile |
| Video | brand-made video ≤90s | only influencer/customer videos, or long brand video | none | A short brand video near the top of the gallery explains the product faster than text |
| Title in search | brand, product type and size in the first 80 characters | brand or size cut off | product type cut off | People choose from truncated titles in mobile search |
| Bullets | all ≤250 characters | some longer | none | Collapsed bullets need to land in the first line |
| A+ on a phone | text is light | 1–2 text-heavy images (>30 words) | 3+ text-heavy, or no A+ | Copy inside stacked images becomes unreadably small |

## Legibility review (needs `m.media-amazon.com` in Allowed domains)
When `heroes[].mobile_sheet` exists, open the PNG. It shows the main image at search-thumbnail size and
every gallery image at phone width. For each best-seller, judge:
- **The thumbnail:** can you tell what the product is and its pack size at 150px? Does the product fill the frame?
- **Callouts:** can every callout be read at phone width without zooming? More than 3–4 callouts per image is too many.
- **The worst image:** name it, e.g. "PT03 ingredient panel".

Write `findings.mobile_review[asin] = {"legible": true|false, "worst_image": "...", "verdict": "one line"}`.
Without a sheet, base the verdict on the A+ text-density check and say legibility wasn't checked.

## How to use it in the pitch
- Fails on a best-seller are strong, concrete email bullets. For example: "Your top seller has no brand video,
  only influencer clips" or "Half your A+ images are unreadable on a phone".
- Group mobile issues into one point unless one alone is the biggest lever.
```

### `.claude/skills/outreach/references/scoring-rubric.md`

```markdown
# Listing scoring rubric

`analyse/rubric.py` applies these thresholds. If you change them, change both. Each check scores
good = 2, warn = 1, fail = 0. A listing's score is its total as a percentage of the maximum.

| Check | Good | Warn | Fail | Why it matters |
|---|---|---|---|---|
| Images | ≥ 7 | 5–6 | < 5 | Unused image slots mean no infographics, lifestyle shots or size and scale images, which lowers conversion |
| Video | ≥ 1 | – | 0 | Video on the listing lifts conversion and lets them run Sponsored Brands Video with listing parity |
| A+ | present | – | none | A brand-registered seller without A+ is leaving free conversion lift and cross-sell modules unused |
| Title | 80–200 chars | outside that range | – | Too short misses indexable keywords; too long gets truncated on mobile |
| Bullets | ≥ 5 | 3–4 | < 3 | Each empty bullet slot loses indexing and objection handling |
| Bullet depth | avg ≥ 120 chars | 70–119 | < 70 | Thin bullets usually mean no benefit-led copy |
| Rating | ≥ 4.3 | 4.0–4.29 | < 4.0 | Below 4.0, ads convert badly and often lose money. Fix the product or listing before scaling spend |
| Reviews | ≥ 100 | 20–99 | < 20 | Low review counts point to Vine or launch support |

Brand-level checks in `content.summary`:
- `share_no_video`, `share_no_aplus`, `share_under_7_images`: report these as "X of their top N
  listings…". A catalogue-wide pattern points to a process fix, which makes a stronger pitch than a single listing.
- `variation_consolidation`: single-ASIN listings that share a title stem. Merging them into one
  variation family pools reviews and ranking. This is a strong point when reviews are split thinly.
- `has_brand_store: false` means no Brand Store was detected. Treat it as a soft signal, because
  Keepa doesn't always return store data. Spot-check before claiming it.

How to prioritise:
- Content problems on the **top 3 revenue ASINs** outrank problems on the long tail.
- A rating below 4.0 on a hero ASIN is a "fix before you scale ads" point. That's a credible,
  non-salesy thing to say.
```

### `.claude/skills/outreach/templates/audit.html`

```html
<title>{{TITLE}}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,500;1,400&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
/* Layout: one reading column; the five recommendations lead, evidence sections follow in the order the email cites them. */
:root {
  --bg: #f6f1e7;
  --paper: #fffdf8;
  --ink: #1a1a18;
  --ink-soft: #4a4842;
  --muted: #7d7a72;
  --rule: #d9d2c3;
  --accent: #d85a30;
  --accent-soft: #f3d9cc;
  --bar: #4a4842;
  --s0: #d85a30; --s1: #2a78d6; --s2: #1baf7a; --s3: #c98500; --s4: #6250d6; --s5: #e87ba4;
  --good: #0a7d0a; --warn: #a86a00; --fail: #c03434;
  --serif: "Lora", Georgia, serif;
  --sans: "Inter", system-ui, -apple-system, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, Menlo, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #191815; --paper: #22201c; --ink: #f0ebe0; --ink-soft: #c9c3b6; --muted: #9a958a; --rule: #3a3731;
    --accent: #ea7a50; --accent-soft: #4a2a1d; --bar: #c9c3b6;
    --s0: #ea7a50; --s1: #3987e5; --s2: #199e70; --s3: #c98500; --s4: #9085e9; --s5: #d55181;
    --good: #3cc23c; --warn: #f0b03a; --fail: #ef6b6b;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #191815; --paper: #22201c; --ink: #f0ebe0; --ink-soft: #c9c3b6; --muted: #9a958a; --rule: #3a3731;
  --accent: #ea7a50; --accent-soft: #4a2a1d; --bar: #c9c3b6;
  --s0: #ea7a50; --s1: #3987e5; --s2: #199e70; --s3: #c98500; --s4: #9085e9; --s5: #d55181;
  --good: #3cc23c; --warn: #f0b03a; --fail: #ef6b6b;
  color-scheme: dark;
}
*, *::before, *::after { box-sizing: border-box; }
body { background: var(--bg); color: var(--ink); font: 400 16px/1.6 var(--sans); -webkit-font-smoothing: antialiased; }
.page { max-width: 980px; margin: 0 auto; padding-block: 40px 64px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 56px; }
a { color: inherit; text-decoration-color: var(--accent); text-underline-offset: 3px; }
h1, h2 { font-family: var(--serif); font-weight: 400; letter-spacing: -0.015em; text-wrap: balance; margin: 0; }
h1 { font-size: clamp(34px, 7vw, 56px); line-height: 1.1; }
h2 { font-size: clamp(26px, 4vw, 34px); line-height: 1.2; }
h3 { font-size: 17px; font-weight: 600; margin: 0; text-wrap: balance; }
p { margin: 0; max-width: 68ch; }
.eyebrow, .tag, .stat-label, th, .tick, small { font-family: var(--mono); }
.eyebrow { font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
section { display: grid; gap: 20px; min-width: 0; }
section > header { display: grid; gap: 8px; border-top: 1px solid var(--rule); padding-top: 24px; }

/* Hero */
.hero { display: grid; gap: 14px; }
.hero .meta { display: flex; flex-wrap: wrap; gap: 8px 18px; color: var(--ink-soft); font-family: var(--mono); font-size: 13px; }
.subject:empty { display: none; }
.subject { font-size: 17px; color: var(--ink-soft); max-width: 70ch; }
.headline { font-family: var(--serif); font-style: italic; font-size: clamp(19px, 2.6vw, 23px); color: var(--ink-soft); max-width: 60ch; }

/* Recommendations: numbered because they are in priority order */
.points { list-style: none; counter-reset: pt; margin: 0; padding: 0; display: grid; gap: 14px; }
.point { counter-increment: pt; display: grid; grid-template-columns: 44px 1fr; gap: 12px; background: var(--paper);
  border: 1px solid var(--rule); border-radius: 14px; padding: 20px 20px 18px 16px; }
.point::before { content: counter(pt); font-family: var(--serif); font-size: 30px; line-height: 1; color: var(--accent); text-align: center; }
.point-body { display: grid; gap: 8px; min-width: 0; }
.tag { font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
.quote { border-left: 2px solid var(--accent); padding-left: 12px; color: var(--ink-soft); font-size: 15px; }
details summary { cursor: pointer; color: var(--ink-soft); font-size: 14px; }
details ul { margin: 8px 0 0; padding-left: 18px; color: var(--ink-soft); font-size: 14px; display: grid; gap: 4px; }

/* Stats */
.stats { break-inside: avoid; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 1px; background: var(--rule);
  border: 1px solid var(--rule); border-radius: 14px; overflow: hidden; }
.stat { background: var(--paper); padding: 16px; display: grid; gap: 4px; align-content: start; }
.stat-label { font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }
.stat-value { font-family: var(--serif); font-size: 28px; line-height: 1.15; font-variant-numeric: tabular-nums; }
.stat-note { font-size: 13px; color: var(--muted); }

/* Charts */
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 24px; }
.two > * { min-width: 0; display: grid; gap: 10px; align-content: start; }
.chart { width: 100%; height: auto; display: block; }
.chart .bar { fill: var(--bar); }
.chart .bar:hover { fill: var(--accent); }
.chart .grid { stroke: var(--rule); stroke-dasharray: 2 4; }
.chart .axis { stroke: var(--muted); }
.chart .tick { fill: var(--muted); font-size: 11px; }
.empty { color: var(--muted); font-style: italic; }
.hbars { display: grid; gap: 8px; }
.hbar { display: grid; grid-template-columns: minmax(90px, 160px) 1fr 52px; gap: 10px; align-items: center; font-size: 14px; }
.hbar-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hbar-track { height: 10px; background: var(--rule); border-radius: 5px; overflow: hidden; }
.hbar-fill { display: block; height: 100%; background: var(--bar); border-radius: 0 4px 4px 0; }
.hbar.mine { font-weight: 600; }
.hbar.mine .hbar-fill { background: var(--accent); }
.hbar-value { text-align: right; font-variant-numeric: tabular-nums; color: var(--ink-soft); }
.stack { display: flex; gap: 2px; height: 18px; border-radius: 4px; overflow: hidden; }
.seg, .sw { background: var(--s0); }
.s1 { background: var(--s1); } .s2 { background: var(--s2); } .s3 { background: var(--s3); } .s4 { background: var(--s4); } .s5 { background: var(--s5); }
.legend { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 14px; }
.legend li { display: flex; align-items: center; gap: 6px; }
.legend small { color: var(--muted); }
.sw { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.budget-total { font-family: var(--serif); font-size: 26px; }

/* Tables */
.scroll { overflow-x: auto; border: 1px solid var(--rule); border-radius: 12px; background: var(--paper); }
table { border-collapse: collapse; width: 100%; font-size: 14px; font-variant-numeric: tabular-nums; }
th { font-size: 11px; font-weight: 500; letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted); text-align: left; }
th, td { padding: 9px 12px; border-bottom: 1px solid var(--rule); vertical-align: top; }
tbody tr:last-child > * { border-bottom: 0; }
td.num, th.num { text-align: right; }
table.content td { white-space: nowrap; }
table.content th[scope="row"] { text-transform: none; letter-spacing: 0; color: var(--ink); font-size: 13px; min-width: 180px; }
table.content th[scope="row"] small { display: block; color: var(--muted); font-family: var(--sans); white-space: normal; }
.chip { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 50%; font-size: 11px; font-weight: 700; color: var(--paper); }
.chip.good { background: var(--good); } .chip.warn { background: var(--warn); } .chip.fail { background: var(--fail); }
.kw-status { font-size: 13px; color: var(--ink-soft); }
.kw-status.push, .kw-status.brand_defence_gap { color: var(--accent); font-weight: 600; }
.attackers { padding-left: 18px; margin: 0; display: grid; gap: 6px; }
.attackers small { display: block; color: var(--muted); font-family: var(--sans); }
ul, ol { margin: 0; padding-left: 20px; display: grid; gap: 6px; }
.method { font-size: 14px; color: var(--ink-soft); display: grid; gap: 10px; }
footer { font-family: var(--mono); font-size: 12px; color: var(--muted); }
.heroes { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; }
.hero-card { background: var(--paper); border: 1px solid var(--rule); border-radius: 14px; padding: 18px;
  display: grid; gap: 12px; align-content: start; min-width: 0; }
.hero-card header { display: grid; gap: 4px; }
.hero-card header a { font-family: var(--mono); font-size: 12px; color: var(--muted); }
.hero-meta { font-size: 13px; color: var(--ink-soft); font-variant-numeric: tabular-nums; }
.hero-card h4 { margin: 0 0 4px; font-family: var(--mono); font-size: 11px; font-weight: 500; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--muted); }
.hero-card ul { padding-left: 0; list-style: none; font-size: 14px; gap: 4px; }
.hero-card ul small, .quick small { display: block; color: var(--muted); }
.hero-card p { font-size: 14px; }
.hero-card .action { font-weight: 600; border-left: 2px solid var(--accent); padding-left: 10px; }
.flags li { display: flex; gap: 8px; align-items: baseline; }
.flags li.verdict { display: block; font-style: italic; color: var(--ink-soft); }
.quick { font-size: 14px; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (max-width: 520px) { .point { grid-template-columns: 1fr; } .point::before { text-align: left; } .hbar { grid-template-columns: 96px 1fr 44px; } }
</style>

<main class="page">
  <div class="hero">
    <span class="eyebrow">{{EYEBROW}}</span>
    <h1>{{BRAND}}</h1>
    <p class="subject">{{SUBJECT}}</p>
    <div class="meta"><span>{{MARKET}}</span><span>Prepared {{DATE}}</span></div>
    <p class="headline">{{HEADLINE}}</p>
  </div>

  <section>
    <header><span class="eyebrow">Priorities</span><h2>What I would do first</h2></header>
    <ol class="points">{{POINTS}}</ol>
  </section>

  <section>
    <header><span class="eyebrow">Snapshot</span><h2>{{SNAPSHOT_TITLE}}</h2></header>
    <div class="stats">{{STATS}}</div>
  </section>

  <section>
    <header><span class="eyebrow">{{HEROES_EYEBROW}}</span><h2>{{HEROES_TITLE}}</h2>
      <p>{{HEROES_INTRO}}</p></header>
    <div class="heroes">{{HEROES}}</div>
  </section>

  {{QUICK_SECTION}}

  <section>
    <header><span class="eyebrow">Listings</span><h2>{{CONTENT_TITLE}}</h2><p>{{CONTENT_NOTE}}</p></header>
    {{CONTENT_TABLE}}
  </section>

  <section>
    <header><span class="eyebrow">Advertising</span><h2>Keyword map and where to spend</h2><p>{{AD_SUMMARY}}</p></header>
    <div class="two">
      <div><h3>Keywords by tier</h3><div class="scroll">{{TIER_TABLE}}</div></div>
      <div><h3>Indicative monthly budget</h3><span class="budget-total">{{BUDGET_TOTAL}}</span>{{BUDGET_CHART}}</div>
    </div>
    <h3>Focus keywords</h3>
    {{KEYWORD_TABLE}}
  </section>

  <section>
    <header><span class="eyebrow">Competitors</span><h2>Who is taking the clicks</h2></header>
    <div class="two">
      <div><h3>Share of voice across category searches</h3>{{SOV_CHART}}</div>
      <div><h3>Ads on their brand name</h3>{{ATTACKERS}}</div>
    </div>
  </section>

  <section>
    <header><span class="eyebrow">Amazon Marketing Cloud</span><h2>Path to purchase and repeat buying</h2></header>
    {{AMC}}
  </section>

  <section>
    <header><span class="eyebrow">Method</span><h2>How this was put together</h2></header>
    <div class="method">{{METHOD}}</div>
  </section>

  <footer>Smart PPC · smartppc.ai</footer>
</main>
```

### `.claude/skills/outreach/templates/email.md`

```markdown
# Outreach email template

The first email names four quick, specific wins, introduces Smart PPC and the open freelance slot,
and offers the detailed report (the audit page) free of charge. It has no link and no attachment. A reply asking for the report is the warm lead.

---

**Subject:** <the most surprising finding, ≤ 8 words. E.g. "Your cleansing balm is listed as a day cream">

Hi <first name>,

I took a quick look at <Brand> on Amazon <UK/US>. <One generous line about what's working, e.g. "Your
best-sellers have great listings">, but four things stood out:

1. **<Product>: <the issue in a few words>.** <One plain sentence on why it matters, e.g. "It's listed
   under Day Care, so it's ranked against moisturisers instead of other cleansing balms.">
2. **<Issue headline>.** <One sentence with a concrete example or number.>
3. **<Issue headline>.** <One sentence, e.g. "It ranks #36 for 'face cleanser' (22,000 searches a month)
   with no ads behind it.">
4. **<Issue headline>.** <One sentence.>

A bit about me: I run Smart PPC, a UK-based Amazon consultancy that combines hands-on account management with AI-powered tools to grow brands on Amazon. I currently have 1 slot available to work with a brand on a freelance basis, fully managing their Amazon account (stock, content, ads and new product development strategy) for £950 a month, with no fixed contracts.

I've put together a more detailed report, product by product, with exactly what I'd change. Happy to
send it across free of charge if it's useful.

If this isn't relevant, just let me know and I won't follow up.

<Signature>

---

## Worked example (Super Facialist, Amazon UK)

**Subject:** Your cleansing balm is listed as a day cream

Hi <first name>,

I took a quick look at Super Facialist on Amazon UK. Your best-sellers have great listings, but four things stood out:

1. **Your Rosehip Cleansing Balm is in the wrong category.** It's listed under Day Care, so it's ranked against moisturisers instead of other cleansing balms.
2. **Some ad spend looks wasted.** Your products are showing ads on searches like "super" and "no 7 foundation", which have nothing to do with them.
3. **Your Vitamin C Cleansing Oil is missing big searches.** It ranks #36 for "face cleanser" (22,000 searches a month) with no ads behind it.
4. **Your Salicylic Face Wash isn't advertised on "face wash"**, which gets 82,000 searches a month and where it already ranks.

A bit about me: I run Smart PPC, a UK-based Amazon consultancy that combines hands-on account management with AI-powered tools to grow brands on Amazon. I currently have 1 slot available to work with a brand on a freelance basis, fully managing their Amazon account (stock, content, ads and new product development strategy) for £950 a month, with no fixed contracts.

I've put together a more detailed report, product by product, with exactly what I'd change. Happy to send it across free of charge if it's useful.

If this isn't relevant, just let me know and I won't follow up.

<Signature>

---

## Rules
- Exactly 4 numbered points, each about a best-seller or the ad account. Order them by revenue at stake.
- Plain English for a brand owner. No "SP", "ACoS", "exact match", "variation family", "SOV".
- Each point has at most one number, rounded and written out (22,000, not 22k).
- Hedge estimates ("looks like", "roughly"). Never say we've seen their account.
- Never: links or attachments, "guaranteed", client names, criticism of their agency or staff.
- Keep the Smart PPC paragraph word for word, unless the user changes the offer, price or slot count.
- Always end with the opt-out line before the signature (UK business email rules, PECR).
- Don't mention discontinued, out-of-stock or tiny products.
```

## 6.2 Entry point

### `run_audit.py`

```python
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
        same = [r["brand"] for r in catalog_rows
                if r.get("brand") and junglescout.norm_brand(r["brand"]) == junglescout.norm_brand(target["brand"])]
        if same:  # canonical spelling only, e.g. "SuperFacialist" -> "Super Facialist"; never a different brand
            target["brand"] = max(set(same), key=same.count)
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
```

## 6.3 Collectors (`collectors/`): data sources

### `collectors/__init__.py`

(empty file: marks the folder as a Python package)

```python

```

### `collectors/ads_bench.py`

```python
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
```

### `collectors/amc_bench.py`

```python
"""Build anonymised AMC category benchmarks from the AMC instances of accounts you manage.

Run monthly, not per prospect:
    python -m collectors.amc_bench --config amc_instances.json --start 2026-04-01 --end 2026-09-30

Per-instance raw results go to runs/.amc/ (gitignored). Only cross-instance medians are written to
benchmarks/amc_<category>.json, and a category with fewer than MIN_INSTANCES is flagged low_sample
so the skill phrases it as a softer hypothesis.

AMC reporting API: https://advertising.amazon.com/API/docs/en-us/guides/amazon-marketing-cloud/
(Endpoint paths below follow the workflowExecutions API; check them against the current docs for
your AMC instance type before the first run.)
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import statistics
import time
import urllib.request
from pathlib import Path

from .common import MARKETPLACES, ROOT, RUNS_DIR, env, http_json, load_env, lwa_access_token, write_json

QUERIES_DIR = ROOT / "amc_queries"
BENCH_DIR = ROOT / "benchmarks"
RAW_DIR = RUNS_DIR / ".amc"
MIN_INSTANCES = 3
QUERIES = ["path_to_purchase", "new_to_brand", "repeat_rate", "ad_type_overlap"]


def _headers(inst: dict, token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Amazon-Advertising-API-ClientId": env("ADS_CLIENT_ID"),
        "Amazon-Advertising-API-AdvertiserId": inst["advertiser_id"],
        "Amazon-Advertising-API-MarketplaceId": MARKETPLACES[inst["marketplace"]]["marketplace_id"],
    }


def run_query(inst: dict, token: str, name: str, start: str, end: str, timeout_s: int = 3600) -> list[dict]:
    host = MARKETPLACES[inst["marketplace"]]["ads_host"]
    base = f"{host}/amc/reporting/{inst['instance_id']}/workflowExecutions"
    headers = _headers(inst, token)
    created = http_json("POST", base, headers=headers, cache=False, body={
        "workflow": {"workflowId": f"apa-{name}", "sqlQuery": (QUERIES_DIR / f"{name}.sql").read_text()},
        "timeWindowType": "EXPLICIT",
        "timeWindowStart": f"{start}T00:00:00",
        "timeWindowEnd": f"{end}T00:00:00",
        "outputFormat": "CSV",
    })
    exec_id = created["workflowExecutionId"]
    deadline = time.time() + timeout_s
    while True:
        status = http_json("GET", f"{base}/{exec_id}", headers=headers, cache=False)
        if status.get("status") == "SUCCEEDED":
            break
        if status.get("status") in {"FAILED", "REJECTED", "CANCELLED"} or time.time() > deadline:
            raise RuntimeError(f"AMC {name} on {inst['label']}: {status.get('status')} {status.get('statusReason')}")
        time.sleep(30)
    urls = http_json("GET", f"{base}/{exec_id}/downloadUrls", headers=headers, cache=False).get("downloadUrls") or []
    rows = []
    for url in urls:
        with urllib.request.urlopen(url, timeout=120) as resp:
            rows += list(csv.DictReader(io.StringIO(resp.read().decode())))
    return rows


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def metrics_from_results(results: dict[str, list[dict]]) -> dict:
    m: dict[str, float | None] = {}

    path = results.get("path_to_purchase") or []
    total = sum(_f(r["users"]) for r in path)
    if total:
        weight = {"0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5+": 5}
        m["avg_touches_before_purchase"] = sum(weight.get(r["touch_bucket"], 0) * _f(r["users"]) for r in path) / total
        m["share_3plus_touches"] = sum(_f(r["users"]) for r in path if r["touch_bucket"] in {"3", "4", "5+"}) / total

    ntb = (results.get("new_to_brand") or [{}])[0]
    if _f(ntb.get("purchases")):
        m["ntb_share"] = _f(ntb.get("ntb_purchases")) / _f(ntb["purchases"])

    rep = (results.get("repeat_rate") or [{}])[0]
    if _f(rep.get("buyers")):
        buyers = _f(rep["buyers"])
        m["repeat_rate"] = _f(rep.get("repeat_buyers")) / buyers
        m["repeat_60d_rate"] = _f(rep.get("repeat_60d")) / buyers
        m["avg_days_to_repeat"] = _f(rep.get("avg_days_to_repeat")) or None

    overlap = results.get("ad_type_overlap") or []
    sp_only = [r for r in overlap if (r["sp"], r["sb"], r["sd"]) == ("1", "0", "0")]
    multi = [r for r in overlap if r["sp"] == "1" and (r["sb"] == "1" or r["sd"] == "1")]

    def cvr(rows):
        exposed = sum(_f(r["exposed_users"]) for r in rows)
        return sum(_f(r["purchasers"]) for r in rows) / exposed if exposed else None

    if (a := cvr(sp_only)) and (b := cvr(multi)):
        m["multi_ad_type_cvr_lift"] = b / a
    return m


def aggregate(per_instance: list[dict]) -> dict:
    keys = sorted({k for inst in per_instance for k in inst["metrics"]})
    out = {}
    for k in keys:
        values = [inst["metrics"][k] for inst in per_instance if inst["metrics"].get(k) is not None]
        if values:
            out[k] = {"median": statistics.median(values), "min": min(values), "max": max(values), "n": len(values)}
    return out


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "amc_instances.json"))
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    args = ap.parse_args()

    instances = json.loads(Path(args.config).read_text())
    tokens: dict[str, str] = {}
    by_category: dict[str, list[dict]] = {}
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    for inst in instances:
        mp = inst["marketplace"]
        if mp not in tokens:
            tokens[mp] = lwa_access_token(env("ADS_REFRESH_TOKEN"), env("ADS_CLIENT_ID"), env("ADS_CLIENT_SECRET"),
                                          MARKETPLACES[mp]["ads_token_host"])
        results = {}
        for q in QUERIES:
            try:
                results[q] = run_query(inst, tokens[mp], q, args.start, args.end)
            except RuntimeError as e:
                print(f"  ! {e}")
        write_json(RAW_DIR / f"{inst['label']}.json", results)
        by_category.setdefault(inst["category"], []).append({"metrics": metrics_from_results(results)})
        print(f"{inst['label']}: {len(results)}/{len(QUERIES)} queries")

    BENCH_DIR.mkdir(exist_ok=True)
    for category, rows in by_category.items():
        slug = re.sub(r"[^a-z0-9]+", "-", category.lower()).strip("-")
        write_json(BENCH_DIR / f"amc_{slug}.json", {
            "category": category,
            "window": [args.start, args.end],
            "instances": len(rows),
            "low_sample": len(rows) < MIN_INSTANCES,
            "metrics": aggregate(rows),
        })
        print(f"benchmarks/amc_{slug}.json ({len(rows)} instances)")


if __name__ == "__main__":
    main()
```

### `collectors/apollo.py`

```python
"""Apollo.io: people currently working at the brand, its parent company or its Amazon seller, with
their LinkedIn profile and (for the top few) a verified work email.

People search is free; revealing an email costs one Apollo credit, so only the best few are enriched.
Docs: https://docs.apollo.io/reference/people-api-search , /reference/people-enrichment ,
      /reference/organization-search
"""
from __future__ import annotations

import re

from .common import Budget, env, http_json, proxy_auth

BASE = "https://api.apollo.io/api/v1"
TITLES = ["founder", "co-founder", "owner", "ceo", "managing director", "director", "head of ecommerce",
          "ecommerce", "amazon", "marketplace", "digital", "head of marketing", "marketing", "brand manager"]
# Lower rank = better person to email about Amazon.
RANKS = [(1, ("founder", "owner", "ceo", "chief executive", "managing director", "md")),
         (2, ("amazon", "marketplace", "ecommerce", "e-commerce", "digital", "online")),
         (3, ("marketing", "brand", "growth", "commercial", "sales")),
         (4, ("director", "head", "manager", "lead"))]


def configured() -> bool:
    return bool(env("APOLLO_API_KEY")) or proxy_auth("apollo")


def _headers() -> dict:
    headers = {"Content-Type": "application/json", "Cache-Control": "no-cache"}
    if env("APOLLO_API_KEY"):
        headers["x-api-key"] = env("APOLLO_API_KEY")
    return headers


def rank(title: str | None) -> int:
    t = (title or "").lower()
    return next((r for r, words in RANKS if any(re.search(rf"\b{re.escape(w)}\b", t) for w in words)), 5)


def _norm(name: str | None) -> str:
    return re.sub(r"\b(ltd|limited|llc|llp|inc|plc|co)\b|[^a-z0-9]", "", (name or "").lower())


def find_orgs(name: str, budget: Budget) -> list[dict]:
    budget.spend("apollo_search")
    resp = http_json("POST", f"{BASE}/mixed_companies/search", headers=_headers(),
                     body={"q_organization_name": name, "page": 1, "per_page": 5})
    return parse_orgs(resp, name)


def parse_orgs(resp: dict, name: str) -> list[dict]:
    """Exact-name matches only: a near miss (e.g. a dissolved namesake) is worse than nothing."""
    out = []
    for o in (resp.get("organizations") or []) + (resp.get("accounts") or []):
        if _norm(o.get("name")) == _norm(name):
            out.append({"id": o.get("id") or o.get("organization_id"), "name": o.get("name"),
                        "domain": o.get("primary_domain") or o.get("website_url"), "linkedin": o.get("linkedin_url")})
    return out


def search_people(budget: Budget, domains: list[str] | None = None, org_ids: list[str] | None = None,
                  per_page: int = 25) -> list[dict]:
    body = {"person_titles": TITLES, "include_similar_titles": True, "page": 1, "per_page": per_page}
    if domains:
        body["q_organization_domains_list"] = domains
    if org_ids:
        body["organization_ids"] = org_ids
    budget.spend("apollo_search")
    resp = http_json("POST", f"{BASE}/mixed_people/api_search", headers=_headers(), body=body)
    return parse_people(resp)


def parse_people(resp: dict) -> list[dict]:
    out = []
    for p in (resp.get("people") or []) + (resp.get("contacts") or []):
        org = p.get("organization") or {}
        name = p.get("name") or " ".join(x for x in (p.get("first_name"), p.get("last_name") or p.get("last_name_obfuscated")) if x)
        out.append({"id": p.get("id"), "name": name, "title": p.get("title"),
                    "organisation": org.get("name") or p.get("organization_name"),
                    "linkedin": p.get("linkedin_url"), "email": p.get("email"),
                    "email_status": p.get("email_status"), "rank": rank(p.get("title"))})
    return sorted(out, key=lambda r: r["rank"])


def enrich(person_id: str, budget: Budget) -> dict:
    """Reveal a verified work email for one person (1 Apollo credit)."""
    budget.spend("apollo_credits")
    resp = http_json("POST", f"{BASE}/people/match", headers=_headers(),
                     body={"id": person_id, "reveal_personal_emails": False, "reveal_phone_number": False})
    p = resp.get("person") or {}
    return {"name": p.get("name"), "linkedin": p.get("linkedin_url"), "email": p.get("email"),
            "email_status": p.get("email_status"), "title": p.get("title")}


def people_for(orgs: list[dict], domain: str | None, budget: Budget, enrich_top: int = 3) -> dict:
    """Current staff across the brand's domain and every organisation name found, best roles first."""
    found, matched = {}, []
    if domain:
        for p in search_people(budget, domains=[domain]):
            found.setdefault(p["id"] or p["name"], {**p, "via": domain})
    for org in orgs:
        for o in find_orgs(org["name"], budget):
            matched.append({**o, "kind": org["kind"]})
            if o["id"]:
                for p in search_people(budget, org_ids=[o["id"]]):
                    found.setdefault(p["id"] or p["name"], {**p, "via": f'{org["kind"]}: {o["name"]}'})
    people = sorted(found.values(), key=lambda r: r["rank"])
    for p in people[:enrich_top]:
        if p.get("id") and not (p.get("email") and p.get("email_status") == "verified"):
            info = enrich(p["id"], budget)
            p.update({k: v for k, v in info.items() if v})
    return {"organisations_matched": matched, "people": people}
```

### `collectors/catalog.py`

```python
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
```

### `collectors/common.py`

```python
"""Shared plumbing for collectors: config, HTTP with caching, per-run budget, run-dir IO."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"
CACHE_DIR = RUNS_DIR / ".cache"
CACHE_TTL_SECONDS = int(os.environ.get("APA_CACHE_TTL", 7 * 24 * 3600))

MARKETPLACES = {
    "us": {
        "domain": "amazon.com",
        "keepa_domain": 1,
        "js": "us",
        "d4s_location": 2840,
        "d4s_language": "en_US",
        "spapi_host": "https://sellingpartnerapi-na.amazon.com",
        "marketplace_id": "ATVPDKIKX0DER",
        "ads_host": "https://advertising-api.amazon.com",
        "ads_token_host": "https://api.amazon.com",
        "currency": "$",
    },
    "uk": {
        "domain": "amazon.co.uk",
        "keepa_domain": 2,
        "js": "uk",
        "d4s_location": 2826,
        "d4s_language": "en_GB",
        "spapi_host": "https://sellingpartnerapi-eu.amazon.com",
        "marketplace_id": "A1F83G8C2ARO7P",
        "ads_host": "https://advertising-api-eu.amazon.com",
        "ads_token_host": "https://api.amazon.co.uk",
        "currency": "£",
    },
}


def load_env(path: Path | None = None) -> None:
    """Minimal .env loader (no dependency). Existing env vars win."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env(name: str) -> str | None:
    value = os.environ.get(name)
    return value or None


def proxy_auth(provider: str) -> bool:
    """True when the cloud environment's agent proxy adds this provider's credentials (a network
    secret), so the session has no key of its own. Set APA_PROXY_AUTH=junglescout,dataforseo."""
    return provider in {p.strip().lower() for p in (env("APA_PROXY_AUTH") or "").split(",")}


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    """Caps paid API usage per run. Units are provider-specific (Keepa tokens, request counts)."""

    limits: dict[str, float] = field(default_factory=lambda: {
        "keepa": float(os.environ.get("APA_BUDGET_KEEPA", 400)),
        "junglescout": float(os.environ.get("APA_BUDGET_JS", 60)),
        "dataforseo": float(os.environ.get("APA_BUDGET_D4S", 40)),
        "spapi": float(os.environ.get("APA_BUDGET_SPAPI", 60)),
        "ads": float(os.environ.get("APA_BUDGET_ADS", 20)),
        "apollo_search": float(os.environ.get("APA_BUDGET_APOLLO_SEARCH", 10)),
        "apollo_credits": float(os.environ.get("APA_BUDGET_APOLLO_CREDITS", 3)),
    })
    used: dict[str, float] = field(default_factory=dict)

    def spend(self, provider: str, units: float = 1) -> None:
        total = self.used.get(provider, 0) + units
        if total > self.limits.get(provider, float("inf")):
            raise BudgetExceeded(f"{provider} budget {self.limits[provider]} exceeded")
        self.used[provider] = total

    def report(self) -> dict:
        return {p: {"used": self.used.get(p, 0), "limit": lim} for p, lim in self.limits.items()}


def _cache_key(method: str, url: str, body) -> Path:
    raw = json.dumps([method, url, body], sort_keys=True, default=str)
    return CACHE_DIR / (hashlib.sha1(raw.encode()).hexdigest() + ".json")


def cached_json(method: str, url: str, params: dict | None = None, body=None):
    """The cached response for a request, or None. Lets rate-limited callers skip waiting on cache hits."""
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(params)}"
    path = _cache_key(method, _strip_secrets(url), body)
    if path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL_SECONDS:
        return json.loads(path.read_text())
    return None


def http_json(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    body=None,
    form: dict | None = None,
    cache: bool = True,
    retries: int = 3,
):
    """JSON request with an on-disk cache so reruns of the same prospect cost nothing."""
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(params)}"
    cache_body = body if body is not None else form
    path = _cache_key(method, _strip_secrets(url), cache_body)
    if cache and path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL_SECONDS:
        return json.loads(path.read_text())

    headers = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers.setdefault("Content-Type", "application/json")
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    headers.setdefault("Accept", "application/json")

    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read()
                if raw[:2] == b"\x1f\x8b":  # Keepa gzips every response, asked or not
                    raw = gzip.decompress(raw)
                text = raw.decode()
                result = json.loads(text) if text else {}
                break
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            last_err = RuntimeError(f"{method} {_strip_secrets(url)} -> {e.code}: {detail}")
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise last_err from None
        except urllib.error.URLError as e:
            last_err = RuntimeError(f"{method} {_strip_secrets(url)} -> {e.reason}")
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise last_err from None
    else:
        raise last_err

    if cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result))
    return result


def _strip_secrets(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    query = [(k, "***" if k.lower() in {"key", "api_key", "token"} else v)
             for k, v in urllib.parse.parse_qsl(parts.query)]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def lwa_access_token(refresh_token: str, client_id: str, client_secret: str,
                     token_host: str = "https://api.amazon.com") -> str:
    """Login-with-Amazon token exchange shared by SP-API and the Ads API."""
    resp = http_json("POST", f"{token_host}/auth/o2/token", cache=False, form={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    })
    return resp["access_token"]


def run_dir(slug: str) -> Path:
    path = RUNS_DIR / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data, indent=2, default=str))
    return path


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]
```

### `collectors/contacts.py`

```python
"""Find the most direct published contacts for a brand from its own website.

Only reports what the brand publishes (emails, founder/director names, company details). Suggested
addresses are produced only when a published personal address reveals the format, and are always
marked unverified. Contacts stay out of audit.html, which is shared with the prospect.
"""
from __future__ import annotations

import re
import urllib.parse

from . import apollo, dataforseo
from .common import Budget

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
COMPANY_NO_RE = re.compile(r"(?:company|registration|registered)\s*(?:no\.?|number|#)\s*[:.]?\s*([A-Z]{0,2}\d{6,8})", re.I)
COMPANY_NAME_RE = re.compile(r"\b((?:[A-Z][A-Za-z0-9&'.\-]* ){1,5}(?:Ltd|Limited|LLP|LLC|Inc|PLC))\b")  # one line only
NAME = r"([A-Z][a-z]+(?:[ '-][A-Z][a-z]+){1,2})"   # case-sensitive: "Jane Smith", never "SHIP RIGHTS"
ROLE = r"(?i:co-?founder|founder|ceo|chief executive|managing director|director|owner)"
PERSON_RES = [
    re.compile(rf"{NAME}\s*[,\-–|(]\s*(?i:our\s+|the\s+)?({ROLE})"),
    re.compile(rf"\b({ROLE})\s*(?i:and\s+\w+\s*)?[,:\-–]?\s*{NAME}"),
    re.compile(rf"(?i:founded by)\s+{NAME}"),
]
BIZDEV = ("wholesale", "trade", "partner", "partnerships", "press", "pr", "marketing", "business", "collab",
          "affiliates", "sales", "stockist", "retail", "amazon", "ecommerce")
GENERIC = ("hello", "info", "support", "help", "customerservice", "customer", "care", "contact", "enquiries",
           "orders", "admin", "team", "service", "returns", "privacy", "dpo", "legal", "noreply", "no-reply",
           "complaints", "vip", "feedback", "billing", "accounts", "jobs", "careers", "unsubscribe", "shop")
CONTACT_PATHS = ["/", "/pages/contact", "/contact", "/contact-us", "/pages/contact-us", "/pages/about",
                 "/pages/about-us", "/about", "/pages/wholesale", "/policies/terms-of-service",
                 "/policies/privacy-policy"]
GENERIC_PREFERRED = ("hello", "info", "contact", "enquiries", "team", "admin")  # read by staff, unlike complaints@/legal@
PLATFORMS = re.compile(r"\b(shopify|google|amazon|paypal|klaviyo|stripe|meta|facebook|apple|microsoft|"
                       r"wix|squarespace|bigcommerce|woocommerce|automattic|trustpilot|yotpo|klarna)\b", re.I)
NOT_NAMES = {"Free Worldwide", "Happy Customers", "Our Story", "Terms Of", "Privacy Policy", "Read More"}


def classify(email: str, people: dict | None = None) -> str:
    """personal = matches a named person; business = bizdev/trade inbox; generic = customer-facing;
    role = any other shared inbox."""
    local = email.split("@")[0].lower()
    for name in people or {}:
        parts = re.sub(r"[^a-z ]", "", name.lower()).split()
        if parts and (parts[0] in local or parts[-1] in local):
            return "personal"
    if any(local == g or local.startswith(g) for g in GENERIC):
        return "generic"
    if any(local == b or local.startswith(b) for b in BIZDEV):
        return "business"
    if re.fullmatch(r"[a-z]+\.[a-z]+", local):
        return "personal"  # first.last style even without a known name
    return "role"


def extract(text: str, domain: str | None = None) -> dict:
    emails = {e.strip(".").lower() for e in EMAIL_RE.findall(text)}
    emails = {e for e in emails if not e.endswith((".png", ".jpg", ".webp", ".gif")) and "example." not in e}
    people = {}
    for rx in PERSON_RES:
        for m in rx.finditer(text):
            groups = m.groups()
            name = next((g for g in groups if g and g[0].isupper() and " " in g and not re.fullmatch(ROLE, g, re.I)), None)
            role = next((g for g in groups if g and re.fullmatch(ROLE, g, re.I)), "founder")
            if name and name not in NOT_NAMES and len(name) <= 40:
                people.setdefault(name, role.lower())
    company_no = COMPANY_NO_RE.search(text)
    company_name = next((m for m in COMPANY_NAME_RE.finditer(text)
                         if not PLATFORMS.search(m.group(1))), None)
    return {"emails": sorted(emails), "people": people,
            "company_number": company_no.group(1) if company_no else None,
            "company_name": company_name.group(1).strip() if company_name else None}


def email_format(emails: list[str], people: dict, domain: str) -> str | None:
    """Infer the address format only from a published personal address that matches a known name."""
    for e in emails:
        local, _, dom = e.partition("@")
        if dom != domain or classify(e, people) != "personal":
            continue
        for name in people:
            first, last = name.lower().split()[0], name.lower().split()[-1]
            for fmt, value in (("{first}.{last}", f"{first}.{last}"), ("{first}{last}", f"{first}{last}"),
                               ("{f}{last}", f"{first[0]}{last}"), ("{first}", first)):
                if local == value:
                    return fmt
    return None


def suggest(people: dict, fmt: str | None, domain: str, known: set[str]) -> list[dict]:
    if not fmt:
        return []
    out = []
    for name in people:
        parts = re.sub(r"[^a-z ]", "", name.lower()).split()
        first, last = parts[0], parts[-1]
        addr = fmt.format(first=first, last=last, f=first[0]) + "@" + domain
        if addr not in known:
            out.append({"name": name, "email": addr, "status": "unverified guess, check before sending"})
    return out


def _generic_rank(email: str) -> int:
    local = email.split("@")[0].lower()
    return next((i for i, g in enumerate(GENERIC_PREFERRED) if local.startswith(g)), len(GENERIC_PREFERRED))


def site_candidates(brand: str, website: str | None) -> list[str]:
    if website:
        return [website if website.startswith("http") else f"https://{website}"]
    slug = re.sub(r"[^a-z0-9]", "", brand.lower())
    return [f"https://{slug}.{tld}" for tld in ("co.uk", "com", "co")]


def find_contacts(brand: str, budget: Budget, website: str | None = None, max_pages: int = 8) -> dict:
    root = None
    for cand in site_candidates(brand, website):
        page = dataforseo.page_text(cand.rstrip("/") + "/", budget)  # the parser needs a path on bare domains
        if page and page["text"].strip():
            root, home = cand.rstrip("/"), page
            break
    if not root:
        return {"website": None, "note": "brand website not found; pass --website"}
    domain = urllib.parse.urlsplit(root).netloc.removeprefix("www.")

    pages = {root + "/": home}
    extra = [l["url"] for l in home["links"]
             if re.search(r"contact|about|story|wholesale|trade|press", l["url"] + " " + l["text"], re.I)
             and domain in l["url"]]
    for url in list(dict.fromkeys([root + p for p in CONTACT_PATHS[1:]] + extra)):
        if len(pages) >= max_pages:
            break
        if url not in pages:
            page = dataforseo.page_text(url, budget)
            if page and page["text"].strip():
                pages[url] = page

    found_emails: dict[str, str] = {}
    people: dict[str, dict] = {}
    company = {"name": None, "number": None}
    for url, page in pages.items():
        x = extract(page["text"], domain)
        for e in x["emails"]:
            found_emails.setdefault(e, url)
        for name, role in x["people"].items():
            people.setdefault(name, {"role": role, "source": url})
        company["name"] = company["name"] or x["company_name"]
        company["number"] = company["number"] or x["company_number"]

    order = {"personal": 0, "business": 1, "role": 2, "generic": 3}
    emails = sorted(({"email": e, "type": classify(e, people), "source": src, "on_domain": e.endswith("@" + domain)}
                     for e, src in found_emails.items()),
                    key=lambda r: (not r["on_domain"], order[r["type"]], _generic_rank(r["email"]), r["email"]))
    fmt = email_format([e["email"] for e in emails], people, domain)
    best = next((e for e in emails if e["on_domain"]), emails[0] if emails else None)
    return {
        "website": root,
        "domain": domain,
        "pages_checked": list(pages),
        "emails": emails,
        "people": [{"name": n, **v} for n, v in people.items()],
        "company": company,
        "email_format": fmt,
        "suggested": suggest(people, fmt, domain, set(found_emails)),
        "recommended_to": best["email"] if best else None,
        "only_generic": bool(emails) and all(e["type"] in ("generic", "role") for e in emails if e["on_domain"]),
    }


# --- research beyond the brand's own site ------------------------------------------------------------

CH = "https://find-and-update.company-information.service.gov.uk"
CH_RESULT_RE = re.compile(r"(?P<number>[A-Z]{0,2}\d{6,8}) - (?P<status>Incorporated on [^\n]+|Dissolved on [^\n]+)\n"
                          r"(?P<address>[^\n]+)\n(?P<name>[^\n]+)")
OFFICER_RE = re.compile(r"^([A-Z][A-Z'\-]+(?: [A-Z][A-Z'\-]+)*, [A-Z][a-z]+(?: [A-Z][a-z]+)*)$", re.M)
LINKEDIN_ROLES = ["founder", "ecommerce", "amazon", "marketing"]


def org_names(brand: str, site_company: str | None, seller: str | None) -> list[dict]:
    """Every name the business trades or registers under: brand, website operator, Amazon seller."""
    out, seen = [], set()
    for name, kind in ((brand, "brand"), (site_company, "website operator"), (seller, "Amazon seller")):
        if name and "amazon" not in name.lower() and norm_key(name) not in seen:
            seen.add(norm_key(name))
            out.append({"name": name, "kind": kind})
    return out


def norm_key(name: str) -> str:
    return re.sub(r"\b(ltd|limited|llc|llp|inc|plc|co)\b|[^a-z0-9]", "", (name or "").lower())


def parse_ch_search(text: str, wanted: str) -> list[dict]:
    """Companies House search results that match the name exactly (ignoring Ltd/punctuation)."""
    out = []
    for m in CH_RESULT_RE.finditer(text):
        if norm_key(m["name"]) == norm_key(wanted):
            out.append({"number": m["number"], "name": m["name"].strip(), "address": m["address"].strip(),
                        "active": m["status"].startswith("Incorporated"), "status": m["status"].strip()})
    return out


def companies_house(name: str, budget: Budget) -> list[dict]:
    """Active UK companies with this exact name, with the people listed on their officers page."""
    page = dataforseo.page_text(f"{CH}/search/companies?q={urllib.parse.quote_plus(name)}", budget)
    matches = [c for c in parse_ch_search((page or {}).get("text", ""), name) if c["active"]]
    for c in matches[:2]:
        officers = dataforseo.page_text(f"{CH}/company/{c['number']}/officers", budget)
        c["people"] = sorted(set(OFFICER_RE.findall((officers or {}).get("text", ""))))
        c["url"] = f"{CH}/company/{c['number']}/officers"
    return matches[:2]


def linkedin_links(orgs: list[dict]) -> list[dict]:
    """One-click LinkedIn people searches; open them while logged in (LinkedIn needs a login)."""
    links = []
    for org in orgs:
        for role in LINKEDIN_ROLES:
            q = f'"{org["name"]}" {role}'
            links.append({"org": org["name"], "role": role,
                          "url": "https://www.linkedin.com/search/results/people/?keywords=" + urllib.parse.quote(q)})
    return links


def web_mentions(brand: str, marketplace: str, budget: Budget, domain: str | None) -> dict:
    """One Google search for the brand: picks up addresses published elsewhere (Instagram bios,
    press pages), plus any LinkedIn profiles that happen to show up."""
    results = dataforseo.google(f'"{brand}" email OR contact OR founder', marketplace, budget)
    emails, profiles = {}, []
    root = (domain or "").split(".")[0]
    for r in results:
        for e in EMAIL_RE.findall(r["title"] + " " + r["description"]):
            e = e.strip(".").lower()
            if root and root in e.split("@")[1]:
                emails.setdefault(e, r["url"])
        if "linkedin.com/in/" in r["url"]:
            name, _, headline = r["title"].partition(" - ")
            profiles.append({"name": name.strip(), "headline": headline.replace("| LinkedIn", "").strip(" -|"),
                             "url": r["url"]})
    return {"emails": emails, "linkedin_profiles": profiles}


def research(brand: str, marketplace: str, budget: Budget, contacts: dict, seller: str | None) -> dict:
    orgs = org_names(brand, (contacts.get("company") or {}).get("name"), seller)
    mentions = web_mentions(brand, marketplace, budget, contacts.get("domain"))
    known = {e["email"] for e in contacts.get("emails", [])}
    for e, src in mentions["emails"].items():
        if e not in known:
            contacts.setdefault("emails", []).append({"email": e, "type": classify(e, {}), "source": src,
                                                      "on_domain": False, "found_via": "web search"})
    order = {"personal": 0, "business": 1, "role": 2, "generic": 3}
    contacts["emails"] = sorted(contacts.get("emails", []), key=lambda r: (order[r["type"]], _generic_rank(r["email"])))
    best = next((e for e in contacts["emails"] if e["type"] in ("personal", "business")), None)
    if best:
        contacts["recommended_to"] = best["email"]
        contacts["only_generic"] = False
    uk = [o for o in orgs if o["kind"] != "brand" or marketplace == "uk"]
    contacts["organisations"] = orgs
    contacts["companies_house"] = [c for o in uk for c in companies_house(o["name"], budget)] if marketplace == "uk" else []
    contacts["linkedin_profiles"] = mentions["linkedin_profiles"]
    if apollo.configured():
        result = apollo.people_for(orgs, contacts.get("domain"), budget)
        contacts["apollo"] = result
        verified = next((p for p in result["people"] if p.get("email") and p.get("email_status") == "verified"), None)
        if verified:
            contacts["recommended_to"] = verified["email"]
            contacts["recommended_person"] = f'{verified["name"]}, {verified.get("title") or ""}'.strip(", ")
            contacts["only_generic"] = False
    contacts["linkedin_searches"] = linkedin_links(orgs)
    return contacts
```

### `collectors/dataforseo.py`

```python
"""DataForSEO: live Amazon SERPs (who is sponsored / ranking) and ranked keywords per ASIN.

Docs: https://docs.dataforseo.com/v3/merchant/amazon/products/  and  /v3/dataforseo_labs/amazon/ranked_keywords/
"""
from __future__ import annotations

import base64
import time

from .common import MARKETPLACES, Budget, env, http_json, proxy_auth

BASE = "https://api.dataforseo.com/v3"
TASK_READY, TASK_PENDING = 20000, {40601, 40602}


def configured() -> bool:
    return bool(env("DATAFORSEO_LOGIN") and env("DATAFORSEO_PASSWORD")) or proxy_auth("dataforseo")


def _headers() -> dict:
    if not env("DATAFORSEO_LOGIN"):
        return {}
    token = base64.b64encode(f"{env('DATAFORSEO_LOGIN')}:{env('DATAFORSEO_PASSWORD')}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def serp(keyword: str, marketplace: str, budget: Budget, depth: int = 48, timeout_s: int = 300) -> dict:
    """Amazon search results page for a keyword. Async task API: post, then poll."""
    mp = MARKETPLACES[marketplace]
    budget.spend("dataforseo")
    posted = http_json("POST", f"{BASE}/merchant/amazon/products/task_post", headers=_headers(), body=[{
        "keyword": keyword, "location_code": mp["d4s_location"], "language_code": mp["d4s_language"],
        "depth": depth, "priority": 2,
    }])
    task_id = posted["tasks"][0]["id"]
    deadline = time.time() + timeout_s
    while True:
        resp = http_json("GET", f"{BASE}/merchant/amazon/products/task_get/advanced/{task_id}",
                         headers=_headers(), cache=False)
        task = resp["tasks"][0]
        if task.get("status_code") == TASK_READY:
            return parse_serp(keyword, resp)
        if task.get("status_code") not in TASK_PENDING or time.time() > deadline:
            raise RuntimeError(f"DataForSEO task {task_id}: {task.get('status_code')} {task.get('status_message')}")
        time.sleep(10)


def parse_serp(keyword: str, resp: dict) -> dict:
    result = ((resp.get("tasks") or [{}])[0].get("result") or [{}])[0]
    items = []
    for it in result.get("items") or []:
        kind = it.get("type", "")
        items.append({
            "asin": it.get("data_asin"),
            "title": it.get("title") or "",
            "position": it.get("rank_absolute"),
            "sponsored": "paid" in kind,
            "type": kind,
            "price": it.get("price_from"),
            "rating": (it.get("rating") or {}).get("value"),
            "reviews": (it.get("rating") or {}).get("votes_count"),
            "is_best_seller": it.get("is_best_seller"),
            "is_amazon_choice": it.get("is_amazon_choice"),
        })
    return {"keyword": keyword, "total_results": result.get("se_results_count"), "items": items}


def ranked_keywords(asin: str, marketplace: str, budget: Budget, limit: int = 200) -> list[dict]:
    """Fallback keyword source when Jungle Scout isn't available."""
    mp = MARKETPLACES[marketplace]
    budget.spend("dataforseo")
    resp = http_json("POST", f"{BASE}/dataforseo_labs/amazon/ranked_keywords/live", headers=_headers(), body=[{
        "asin": asin, "location_code": mp["d4s_location"], "language_code": mp["d4s_language"], "limit": limit,
    }])
    return parse_ranked(resp)


def parse_ranked(resp: dict) -> list[dict]:
    result = ((resp.get("tasks") or [{}])[0].get("result") or [{}])[0]
    rows = []
    for it in result.get("items") or []:
        kd = it.get("keyword_data") or {}
        serp_item = (it.get("ranked_serp_element") or {}).get("serp_item") or {}
        paid = "paid" in (serp_item.get("type") or "")
        rows.append({
            "keyword": kd.get("keyword"),
            "volume": (kd.get("keyword_info") or {}).get("search_volume") or 0,
            "organic_rank": None if paid else serp_item.get("rank_absolute"),
            "sponsored_rank": serp_item.get("rank_absolute") if paid else None,
            "relevancy": None,
            "cpc_exact": None,
            "source": "dataforseo",
        })
    return rows


def page_text(url: str, budget: Budget) -> dict | None:
    """Fetch and parse any web page through DataForSEO (our network can't reach brand sites directly).
    Returns {"url", "text", "links"} or None when the page doesn't exist."""
    budget.spend("dataforseo", 0.1)  # ~$0.00015 a page; counted as a tenth of a search task
    resp = http_json("POST", f"{BASE}/on_page/content_parsing/live", headers=_headers(), body=[{"url": url}])
    return parse_page(url, resp)


def parse_page(url: str, resp: dict) -> dict | None:
    task = (resp.get("tasks") or [{}])[0]
    item = ((task.get("result") or [{}])[0].get("items") or [None])[0]
    if not item or (item.get("status_code") or 0) >= 400:
        return None
    texts, links = [], []

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("text"), str):
                texts.append(node["text"])
            for u in node.get("urls") or []:
                if isinstance(u, dict) and u.get("url"):
                    links.append({"url": u["url"], "text": u.get("anchor_text") or ""})
            for v in node.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(item.get("page_content") or {})
    return {"url": url, "text": "\n".join(texts), "links": links}


def google(query: str, marketplace: str, budget: Budget, depth: int = 20) -> list[dict]:
    """Google results for a query (about $0.01 each): [{"title", "url", "description"}]."""
    mp = MARKETPLACES[marketplace]
    budget.spend("dataforseo")
    resp = http_json("POST", f"{BASE}/serp/google/organic/live/regular", headers=_headers(), body=[{
        "keyword": query, "location_code": mp["d4s_location"], "language_code": "en", "depth": depth}])
    task = (resp.get("tasks") or [{}])[0]
    items = ((task.get("result") or [{}])[0] or {}).get("items") or []
    return [{"title": i.get("title") or "", "url": i.get("url") or "", "description": i.get("description") or ""}
            for i in items if i.get("type") == "organic"]
```

### `collectors/images.py`

```python
"""Download best-seller gallery images and lay them out at phone size, so the skill can judge whether
callouts are readable on a mobile screen and whether the main image works as a search thumbnail.

Images live on m.media-amazon.com; if the environment blocks it, the step is skipped (ImagesBlocked).
"""
from __future__ import annotations

import io
import urllib.error
import urllib.request
from pathlib import Path

CDN = "https://m.media-amazon.com/images/I/"
PHONE_W = 375          # CSS width of a typical phone screen
THUMB_W = 150          # roughly a search-result thumbnail
GAP = 12


class ImagesBlocked(RuntimeError):
    pass


def fetch(file: str) -> bytes:
    try:
        with urllib.request.urlopen(CDN + file, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, OSError) as e:
        raise ImagesBlocked(f"can't reach m.media-amazon.com ({e}); add it to Allowed domains") from e


def phone_sheet(images: list[dict], out: Path, fetcher=fetch) -> Path | None:
    """Main image at thumbnail size, then every gallery image at phone width, in one PNG."""
    from PIL import Image, ImageDraw

    tiles = []
    for img in images:
        file = img.get("medium") or img.get("file")
        if not file:
            continue
        try:
            im = Image.open(io.BytesIO(fetcher(file))).convert("RGB")
        except urllib.error.HTTPError:
            continue
        tiles.append((img.get("variant") or "", im))
    if not tiles:
        return None

    def fit(im, w):
        return im.resize((w, round(im.height * w / im.width)))

    thumb = fit(tiles[0][1], THUMB_W)
    phones = [(label, fit(im, PHONE_W)) for label, im in tiles]
    cols = 3
    rows = (len(phones) + cols - 1) // cols
    row_h = max(p.height for _, p in phones) + 28
    width = cols * (PHONE_W + GAP) + GAP
    height = thumb.height + 48 + rows * row_h + GAP
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((GAP, 8), "Search thumbnail (main image at ~150px)", fill="black")
    sheet.paste(thumb, (GAP, 26))
    y0 = thumb.height + 48
    for i, (label, im) in enumerate(phones):
        x = GAP + (i % cols) * (PHONE_W + GAP)
        y = y0 + (i // cols) * row_h
        draw.text((x, y), f"{label} at phone width ({PHONE_W}px)", fill="black")
        sheet.paste(im, (x, y + 18))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out
```

### `collectors/junglescout.py`

```python
"""Jungle Scout API: sales estimates, keywords by ASIN (incl. organic/sponsored rank + PPC bids), share of voice.

Docs: https://developer.junglescout.com/api
"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse
from collections import defaultdict

from .common import MARKETPLACES, Budget, chunks, env, http_json, proxy_auth

BASE = "https://developer.junglescout.com/api"


def configured() -> bool:
    return bool(env("JS_KEY") and env("JS_KEY_NAME")) or proxy_auth("junglescout")


def _headers() -> dict:
    headers = {
        "X_API_Type": "junglescout",
        "Accept": "application/vnd.junglescout.v1+json",
        "Content-Type": "application/vnd.api+json",
    }
    if env("JS_KEY") and env("JS_KEY_NAME"):
        headers["Authorization"] = f"{env('JS_KEY_NAME')}:{env('JS_KEY')}"
    return headers


def norm_brand(s: str | None) -> str:
    """'Super Facialist', 'SuperFacialist', 'super-facialist' all compare equal."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def product_database(brand: str, marketplace: str, budget: Budget, max_pages: int = 5,
                     alt_spellings: list[str] | None = None) -> list[dict]:
    """Search every spelling (e.g. 'Super Facialist' and 'SuperFacialist') and merge by ASIN."""
    rows: dict[str, dict] = {}
    for name in dict.fromkeys([brand, *(alt_spellings or [])]):
        for r in _product_database(name, marketplace, budget, max_pages):
            rows.setdefault(r["asin"], r)
    names = [n for n in [brand, *(alt_spellings or [])] if n]
    return [r for r in rows.values() if any(brand_matches(r, n) for n in names)]


def brand_matches(row: dict, name: str) -> bool:
    """Brand field equal (ignoring spacing), or the brand as a whole word in the title. Short names like 'W7'
    must never match inside other words ('W70 x L84' curtains)."""
    want = norm_brand(name)
    if not want:
        return False
    if norm_brand(row.get("brand")) == want:
        return True
    if len(want) <= 3:  # 'W7' is also a shoe size: only trust a title that starts with the brand
        return bool(re.match(rf"\s*{re.escape(name)}(?![A-Za-z0-9])", row.get("title") or "", re.I))
    if len(want) <= 4:
        return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", row.get("title") or "", re.I))
    return want in norm_brand(row.get("brand")) or want in norm_brand(row.get("title"))


def _product_database(brand: str, marketplace: str, budget: Budget, max_pages: int = 5) -> list[dict]:
    """Every ASIN Jungle Scout knows for the brand, with 30-day sales, sellers and Buy Box owner.
    One call per 100 products, so it is the cheap way to map a whole catalogue."""
    rows, cursor = [], None
    for _ in range(max_pages):
        budget.spend("junglescout")
        params = {"marketplace": MARKETPLACES[marketplace]["js"], "sort": "-revenue", "page[size]": 100}
        if cursor:
            params["page[cursor]"] = cursor
        resp = http_json("POST", f"{BASE}/product_database_query", headers=_headers(), params=params, body={
            "data": {"type": "product_database_query", "attributes": {
                "include_keywords": [brand], "exclude_unavailable_products": False}}})
        rows += parse_products(resp)
        nxt = (resp.get("links") or {}).get("next")
        cursor = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(nxt).query)).get("page[cursor]") if nxt else None
        if not cursor:
            break
    return rows


def parse_products(resp: dict) -> list[dict]:
    rows = []
    for item in resp.get("data") or []:
        a = item.get("attributes") or {}
        asin = (item.get("id") or "").split("/")[-1]
        rows.append({
            "asin": asin,
            "parent_asin": a.get("parent_asin") or asin,
            "title": a.get("title") or "",
            "brand": a.get("brand"),
            "category": a.get("category"),
            "price": a.get("price"),
            "units_30d": a.get("approximate_30_day_units_sold"),
            "revenue_30d": a.get("approximate_30_day_revenue"),
            "sellers": a.get("number_of_sellers"),
            "buy_box_owner": a.get("buy_box_owner"),
            "seller_type": a.get("seller_type"),
            "rating": a.get("rating"),
            "reviews": a.get("reviews"),
            "listing_quality": a.get("listing_quality_score"),
            "available": a.get("is_available"),
            "date_first_available": a.get("date_first_available"),
            "source": "junglescout",
        })
    return rows


def sales_estimates(asin: str, marketplace: str, budget: Budget, months: int = 12) -> dict:
    """Daily unit estimates rolled up to months: {month: {"units": n, "revenue": r}}."""
    budget.spend("junglescout")
    end = dt.date.today() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=30 * months)
    resp = http_json("GET", f"{BASE}/sales_estimates_query", headers=_headers(), params={
        "marketplace": MARKETPLACES[marketplace]["js"], "asin": asin,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
    })
    return parse_sales(resp)


def parse_sales(resp: dict) -> dict:
    monthly: dict[str, dict] = defaultdict(lambda: {"units": 0.0, "revenue": 0.0})
    for row in resp.get("data") or []:
        for day in (row.get("attributes") or {}).get("data") or []:
            units = day.get("estimated_units_sold") or 0
            price = day.get("last_known_price") or 0
            m = monthly[day["date"][:7]]
            m["units"] += units
            m["revenue"] += units * price
    return {k: {"units": round(v["units"]), "revenue": round(v["revenue"], 2)} for k, v in sorted(monthly.items())}


def keywords_for_asin(asin: str, marketplace: str, budget: Budget, per_page: int = 100) -> list[dict]:
    """Keywords for one hero ASIN, tagged with it, so ranks and wasted terms are per product."""
    return [{**row, "asin": asin} for row in keywords_by_asin([asin], marketplace, budget, per_page)]


def keywords_by_asin(asins: list[str], marketplace: str, budget: Budget, per_page: int = 100,
                     min_volume: int = 100) -> list[dict]:
    out = []
    for batch in chunks(asins, 10):
        budget.spend("junglescout")
        resp = http_json("POST", f"{BASE}/keywords/keywords_by_asin_query", headers=_headers(), params={
            "marketplace": MARKETPLACES[marketplace]["js"], "page[size]": per_page,
            "sort": "-monthly_search_volume_exact",
        }, body={"data": {"type": "keywords_by_asin_query", "attributes": {
            "asins": batch, "include_variants": True, "min_monthly_search_volume_exact": min_volume,
        }}})
        out.extend(parse_keywords(resp))
    return out


def parse_keywords(resp: dict) -> list[dict]:
    rows = []
    for item in resp.get("data") or []:
        a = item.get("attributes") or {}
        rows.append({
            "keyword": a.get("name") or item.get("id", "").split("/", 1)[-1],
            "volume": a.get("monthly_search_volume_exact") or 0,
            "volume_broad": a.get("monthly_search_volume_broad") or 0,
            "organic_rank": a.get("organic_rank"),
            "sponsored_rank": a.get("sponsored_rank"),
            "relevancy": a.get("relevancy_score"),
            "ease_of_ranking": a.get("ease_of_ranking_score"),
            "cpc_exact": a.get("ppc_bid_exact"),
            "cpc_broad": a.get("ppc_bid_broad"),
            "sb_bid": a.get("sp_brand_ad_bid"),
            "sponsored_product_count": a.get("sponsored_product_count"),
            "competitor_ranks": a.get("competitor_organic_rank") or [],
            "source": "junglescout",
        })
    return rows


def share_of_voice(keyword: str, marketplace: str, budget: Budget) -> dict:
    budget.spend("junglescout")
    resp = http_json("GET", f"{BASE}/share_of_voice", headers=_headers(), params={
        "marketplace": MARKETPLACES[marketplace]["js"], "keyword": keyword,
    })
    return parse_sov(keyword, resp)


def parse_sov(keyword: str, resp: dict) -> dict:
    a = (resp.get("data") or {}).get("attributes") or {}
    brands = [{
        "brand": b.get("brand"),
        "sov": b.get("combined_weighted_sov") or 0,
        "organic_sov": b.get("organic_weighted_sov") or 0,
        "sponsored_sov": b.get("sponsored_weighted_sov") or 0,
        "sponsored_products": b.get("sponsored_products") or 0,
        "avg_price": b.get("combined_average_price"),
    } for b in a.get("brands") or []]
    brands.sort(key=lambda b: b["sov"], reverse=True)
    return {
        "keyword": keyword,
        "volume_30d": a.get("estimated_30_day_search_volume"),
        "suggested_bid_median": a.get("exact_suggested_bid_median"),
        "brands": brands,
    }
```

### `collectors/keepa.py`

```python
"""Keepa: ASIN discovery (brand / seller storefront) and per-ASIN listing + history data.

Docs: https://keepa.com/#!discuss/t/product-object/116  (csv indices, Keepa time)
"""
from __future__ import annotations

import datetime as dt
import json
import math
import time

from .common import MARKETPLACES, Budget, cached_json, env, http_json

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
    hit = cached_json("GET", f"{BASE}/{path}", {"key": _key(), **params})
    if hit is not None:  # already paid for: no tokens, no waiting
        return hit
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
        try:
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
        except RuntimeError as e:
            if out and "APA_KEEPA_MAX_WAIT_MIN" in str(e):
                print(f"    … stopping Keepa early; keeping {len(out)} products ({e})", flush=True)
                break
            raise
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
        # mobile checks: image sizes (zoom), video makers and lengths, A+ alt text (text density), bullet text
        "images_detail": [{"file": i.get("l"), "medium": i.get("m"), "w": i.get("lW"), "h": i.get("lH"),
                           "variant": i.get("variant")} for i in p.get("images") or [] if isinstance(i, dict)],
        "videos_detail": [{"creator": v.get("creator"), "duration": v.get("duration"), "title": v.get("title")}
                          for v in p.get("videos") or []],
        "aplus_alt": [alt for m in p.get("aPlus") or [] if isinstance(m, dict)
                      for mod in (m.get("module") if isinstance(m.get("module"), list) else [])
                      if isinstance(mod, dict) for alt in mod.get("imageAltText") or [] if alt],
        "features": features,
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
```

### `collectors/resolve.py`

```python
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
```

## 6.4 Analysis, rendering, PDF and saving (`analyse/`)

### `analyse/__init__.py`

(empty file: marks the folder as a Python package)

```python

```

### `analyse/build_dataset.py`

```python
"""Merge a run's collector output into one dataset.json the skill reasons over.

Everything numeric is computed here, deterministically, so the skill's write-up only interprets.
Assumptions used for estimates are written into the dataset so they can be shown on the audit page.
"""
from __future__ import annotations

import datetime as dt
import re
import statistics
from collections import defaultdict
from pathlib import Path

from collectors.common import MARKETPLACES, ROOT, RUNS_DIR, read_json

from . import checks, mobile
from .rubric import check_listing

# --- assumptions (surfaced on the audit page) -------------------------------------------------
CLICKS_PER_SEARCH = {"low": 0.08, "mid": 0.12, "high": 0.20}   # share of searches producing an ad click
TARGET_SPONSORED_SOV = {"brand": 0.50, "core": 0.20, "category": 0.10, "long_tail": 0.15, "competitor": 0.05}
AD_TYPE_SPLIT = {
    "brand": {"SP": 0.5, "SB": 0.5},
    "core": {"SP": 0.6, "SB": 0.2, "SBV": 0.2},
    "category": {"SP": 0.5, "SB": 0.25, "SBV": 0.25},
    "long_tail": {"SP": 1.0},
    "competitor": {"SP": 0.6, "SD": 0.4},
}
TOP_OF_PAGE, PAGE_ONE, PAGE_TWO = 4, 20, 60
CONSUMABLE_CATEGORIES = re.compile(
    r"beauty|health|grocery|food|pet|baby|household|personal care|drugstore|vitamin|supplement|"
    r"cleaning|coffee|tea|snack|beverage|cosmetic|skin|hair|oral", re.I)
MULTIPACK = re.compile(r"\bpack of\b|\b\d+\s*[x×]\b|\b\d+[- ]pack\b|\bset of\b|\bbundle\b|\bmulti-?pack\b", re.I)


# --- helpers used during collection ----------------------------------------------------------

def _revenue_proxy(p: dict) -> float:
    if p.get("monthly_sold") and p.get("price"):
        return p["monthly_sold"] * p["price"]
    return 1e6 / p["sales_rank"] if p.get("sales_rank") else 0.0


def top_parents(products: list[dict], n: int) -> list[str]:
    """Best-selling child ASIN of each of the top-n parents (keyword tools want a live child)."""
    best: dict[str, dict] = {}
    for p in products:
        parent = p.get("parent_asin") or p["asin"]
        if parent not in best or _revenue_proxy(p) > _revenue_proxy(best[parent]):
            best[parent] = p
    ranked = sorted(best.values(), key=_revenue_proxy, reverse=True)
    return [p["asin"] for p in ranked[:n]]


def merge_keywords(rows: list[dict]) -> list[dict]:
    """Dedupe keywords across ASINs/sources: best rank, max volume, first known bid/relevancy."""
    merged: dict[str, dict] = {}
    for r in rows:
        kw = (r.get("keyword") or "").strip().lower()
        if not kw:
            continue
        m = merged.setdefault(kw, {**r, "keyword": kw})
        for rank in ("organic_rank", "sponsored_rank"):
            vals = [v for v in (m.get(rank), r.get(rank)) if v]
            m[rank] = min(vals) if vals else None
        m["volume"] = max(m.get("volume") or 0, r.get("volume") or 0)
        for k in ("relevancy", "cpc_exact", "cpc_broad", "sb_bid", "ease_of_ranking"):
            if m.get(k) is None and r.get(k) is not None:
                m[k] = r[k]
    return sorted(merged.values(), key=lambda k: k["volume"], reverse=True)


# --- sections ---------------------------------------------------------------------------------

def _asin_map(products: list[dict], discovered: int) -> dict:
    rows = []
    for p in products:
        rows.append({k: p.get(k) for k in ("asin", "parent_asin", "title", "price", "rating", "review_count",
                                            "monthly_sold", "sales_rank", "listed_since", "root_category")}
                    | {"est_monthly_revenue": round(p["monthly_sold"] * p["price"]) if p.get("monthly_sold") and p.get("price") else None})
    rows.sort(key=lambda r: (r["est_monthly_revenue"] or 0, -(r["sales_rank"] or 1e9)), reverse=True)
    return {
        "discovered": discovered,
        "fetched": len(products),
        "parents": len({p.get("parent_asin") or p["asin"] for p in products}),
        "categories": _counts(p.get("root_category") for p in products),
        "asins": rows,
    }


def _counts(values) -> dict:
    out: dict = defaultdict(int)
    for v in values:
        if v:
            out[v] += 1
    return dict(sorted(out.items(), key=lambda kv: kv[1], reverse=True))


def _quarter(day: str) -> str:
    d = dt.date.fromisoformat(day)
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def _catalogue(products: list[dict], js_sales: dict, top_asins: list[str]) -> dict:
    today = dt.date.today()
    cutoff = today.replace(year=today.year - 3).isoformat()
    launches = _counts(_quarter(p["listed_since"]) for p in products
                       if p.get("listed_since") and p["listed_since"] >= cutoff)
    launches = dict(sorted(launches.items()))
    last_12m = sum(v for q, v in launches.items() if q >= _quarter(today.replace(year=today.year - 1).isoformat()))

    revenue_monthly: dict[str, float] = defaultdict(float)
    for series in (js_sales or {}).values():
        for month, v in (series or {}).items():
            revenue_monthly[month] += v.get("revenue") or 0
    current_month = today.strftime("%Y-%m")
    revenue_monthly = {m: round(v) for m, v in sorted(revenue_monthly.items()) if m < current_month}

    yoy = None
    months = list(revenue_monthly)
    if len(months) >= 12:
        recent = sum(revenue_monthly[m] for m in months[-3:])
        year_ago = sum(revenue_monthly[m] for m in months[-12:-9])
        yoy = round((recent / year_ago - 1) * 100) if year_ago else None

    est = sorted((_revenue_proxy(p) if p.get("monthly_sold") else 0 for p in products), reverse=True)
    total_est = sum(est)

    bsr_trend = None
    tops = [p for p in products if p["asin"] in top_asins]
    if tops:
        def median_bsr(offset_months: int):
            month = (today.replace(day=1) - dt.timedelta(days=30 * offset_months)).strftime("%Y-%m")
            vals = [p["history"]["bsr_monthly"].get(month) for p in tops]
            vals = [v for v in vals if v]
            return statistics.median(vals) if vals else None
        now_bsr, then_bsr = median_bsr(1), median_bsr(13)
        if now_bsr and then_bsr:
            bsr_trend = {"median_bsr_now": now_bsr, "median_bsr_year_ago": then_bsr,
                         "improved": now_bsr < then_bsr, "change_pct": round((now_bsr / then_bsr - 1) * 100)}

    reviews_gained = 0
    for p in products:
        hist = p.get("history", {}).get("reviews_monthly") or {}
        if hist:
            months_sorted = sorted(hist)
            year_ago = [m for m in months_sorted if m <= (today.replace(year=today.year - 1)).strftime("%Y-%m")]
            base = hist[year_ago[-1]] if year_ago else 0
            reviews_gained += max(0, hist[months_sorted[-1]] - base)

    return {
        "asin_count": len(products),
        "launches_by_quarter": launches,
        "launches_last_12m": last_12m,
        "revenue_monthly_top_parents": revenue_monthly,
        "revenue_yoy_pct_last_3m": yoy,
        "est_monthly_revenue_keepa": round(total_est) if total_est else None,
        "top3_revenue_share": round(sum(est[:3]) / total_est, 2) if total_est else None,
        "bsr_trend_top_parents": bsr_trend,
        "reviews_gained_12m": int(reviews_gained),
    }


def _content(products: list[dict], top_asins: list[str], catalog_items: list[dict]) -> dict:
    by_asin = {p["asin"]: p for p in products}
    spapi = {i["asin"]: i for i in catalog_items or []}
    parents = []
    for asin in top_asins:
        p = dict(by_asin.get(asin) or {"asin": asin})
        if asin in spapi:  # SP-API image/bullet counts are authoritative when present
            for k in ("image_count", "bullet_count", "bullet_avg_len"):
                if spapi[asin].get(k):
                    p[k] = spapi[asin][k]
        result = check_listing(p)
        parents.append({"asin": asin, "title": p.get("title"), **result})

    def share(pred) -> float | None:
        return round(sum(1 for p in products if pred(p)) / len(products), 2) if products else None

    # Single-ASIN listings that look like they should be one variation family
    singles = [p for p in products if (p.get("parent_asin") or p["asin"]) == p["asin"] and not p.get("variation_count")]
    stems: dict[str, list[str]] = defaultdict(list)
    for p in singles:
        stem = " ".join(re.findall(r"[a-z0-9]+", (p.get("title") or "").lower())[:4])
        if stem:
            stems[stem].append(p["asin"])
    consolidation = [{"title_stem": s, "asins": a} for s, a in stems.items() if len(a) > 1]

    return {
        "summary": {
            "avg_score_top_parents": round(statistics.mean(p["score"] for p in parents)) if parents else None,
            "share_under_7_images": share(lambda p: (p.get("image_count") or 0) < 7),
            "share_no_video": share(lambda p: not p.get("video_count")),
            "share_no_aplus": share(lambda p: not p.get("has_aplus")),
            "share_under_5_bullets": share(lambda p: (p.get("bullet_count") or 0) < 5),
            "share_rating_below_4_2": share(lambda p: p.get("rating") is not None and p["rating"] < 4.2),
            "has_brand_store": any(p.get("brand_store") for p in products) if products else None,
        },
        "top_parents": parents,
        "variation_consolidation": consolidation,
    }


def _has_brand(text: str | None, brand: str) -> bool:
    """Spacing/case-insensitive: 'Superfacialist' matches brand 'Super Facialist'."""
    b = checks.norm(brand)
    return bool(b) and b in checks.norm(text)


def _is_ours(item: dict, our_asins: set[str], brand: str) -> bool:
    return item.get("asin") in our_asins or _has_brand(item.get("title"), brand)


def _guess_brand(title: str) -> str:
    words = (title or "").split()
    return " ".join(words[:2]) if words else "unknown"


def _competitors(sov: list[dict], serps: dict, brand: str, our_asins: set[str], prev_sov: list[dict] | None) -> dict:
    agg: dict[str, dict] = defaultdict(lambda: {"sov": 0.0, "sponsored_sov": 0.0, "keywords": 0})
    category_sov = [s for s in sov if not _has_brand(s["keyword"], brand)]
    for s in category_sov:
        for b in s["brands"]:
            a = agg[b["brand"] or "unknown"]
            a["sov"] += _frac(b["sov"])
            a["sponsored_sov"] += _frac(b["sponsored_sov"])
            a["keywords"] += 1
    n = len(category_sov) or 1
    table = sorted(({"brand": k, "avg_sov": round(v["sov"] / n, 3), "avg_sponsored_sov": round(v["sponsored_sov"] / n, 3),
                     "keywords_present": v["keywords"]} for k, v in agg.items()), key=lambda r: r["avg_sov"], reverse=True)
    for r in table:
        r["is_prospect"] = _has_brand(r["brand"], brand)

    sov_change = None
    if prev_sov:
        prev = _competitors(prev_sov, {}, brand, our_asins, None)["share_of_voice"]
        prev_map = {r["brand"]: r["avg_sov"] for r in prev}
        sov_change = [{"brand": r["brand"], "change": round(r["avg_sov"] - prev_map.get(r["brand"], 0), 3)}
                      for r in table[:15]]
        sov_change.sort(key=lambda r: r["change"], reverse=True)

    brand_attackers, ours_sponsored_on_brand = [], False
    positioning = {"our_prices": [], "our_ratings": [], "comp_prices": [], "comp_ratings": []}
    for s in (serps or {}).get("serps", []):
        is_brand_term = s["keyword"] in (serps.get("brand_terms") or [])
        for it in s["items"]:
            ours = _is_ours(it, our_asins, brand)
            if is_brand_term and it["sponsored"]:
                if ours:
                    ours_sponsored_on_brand = True
                else:
                    brand_attackers.append({"keyword": s["keyword"], "asin": it["asin"], "brand_guess": _guess_brand(it["title"]),
                                            "title": it["title"][:90], "position": it["position"]})
            if not is_brand_term and not it["sponsored"] and (it.get("position") or 99) <= 20:
                key = "our" if ours else "comp"
                if it.get("price"):
                    positioning[f"{key}_prices"].append(it["price"])
                if it.get("rating"):
                    positioning[f"{key}_ratings"].append(it["rating"])

    med = lambda xs: round(statistics.median(xs), 2) if xs else None  # noqa: E731
    return {
        "share_of_voice": table[:15],
        "sov_change_vs_last_run": sov_change,
        "brand_term_attackers": brand_attackers,
        "prospect_sponsored_on_own_brand": ours_sponsored_on_brand,
        "positioning_page1": {
            "our_median_price": med(positioning["our_prices"]), "competitor_median_price": med(positioning["comp_prices"]),
            "our_median_rating": med(positioning["our_ratings"]), "competitor_median_rating": med(positioning["comp_ratings"]),
        },
    }


def _frac(v) -> float:
    v = v or 0
    return v / 100 if v > 1 else v


def _tier(kw: dict, brand: str, competitor_names: set[str], relevancy_cut: float | None) -> str:
    k = kw["keyword"]
    if _has_brand(k, brand):
        return "brand"
    if any(c in k for c in competitor_names):
        return "competitor"
    if len(k.split()) >= 4 or (kw.get("volume") or 0) < 500:
        return "long_tail"
    rel = kw.get("relevancy")
    if (kw.get("organic_rank") or 999) <= PAGE_ONE or (rel is not None and relevancy_cut is not None and rel >= relevancy_cut):
        return "core"
    return "category"


def _status(kw: dict) -> str:
    org, spo = kw.get("organic_rank"), kw.get("sponsored_rank")
    if org and org <= TOP_OF_PAGE:
        return "own" if spo else "organic_top_unprotected"
    if org and org <= PAGE_TWO:
        return "sponsored_support" if spo else "push"
    if spo:
        return "sponsored_only"
    return "missing"


GAP_WEIGHT = {"push": 1.0, "missing": 0.6, "organic_top_unprotected": 0.5, "sponsored_only": 0.4,
              "sponsored_support": 0.3, "own": 0.1}


def _cpc(kw: dict, bids: dict, sov_by_kw: dict) -> float | None:
    if kw["keyword"] in bids:
        return bids[kw["keyword"]]["suggested"]
    for k in ("cpc_exact", "cpc_broad"):
        if kw.get(k):
            return kw[k]
    return (sov_by_kw.get(kw["keyword"]) or {}).get("suggested_bid_median")


def _strategy(keywords: list[dict], sov: list[dict], bids: dict, brand: str, competitor_names: set[str],
              attacked_brand_terms: set[str], products: list[dict]) -> dict:
    sov_by_kw = {s["keyword"]: s for s in sov}
    rels = sorted(k["relevancy"] for k in keywords if k.get("relevancy") is not None)
    relevancy_cut = rels[int(len(rels) * 0.75)] if rels else None

    kmap = []
    for kw in keywords:
        tier = _tier(kw, brand, competitor_names, relevancy_cut)
        status = _status(kw)
        if tier == "brand" and kw["keyword"] in attacked_brand_terms and status in {"organic_top_unprotected", "missing"}:
            status = "brand_defence_gap"
        cpc = _cpc(kw, bids, sov_by_kw)
        gap = 1.0 if status == "brand_defence_gap" else GAP_WEIGHT.get(status, 0.3)
        tier_weight = {"brand": 1.0, "core": 1.0, "category": 0.7, "long_tail": 0.5, "competitor": 0.3}[tier]
        priority = (kw.get("volume") or 0) * tier_weight * gap / max(cpc or 1.0, 0.2)
        kmap.append({"keyword": kw["keyword"], "tier": tier, "volume": kw.get("volume"), "organic_rank": kw.get("organic_rank"),
                     "sponsored_rank": kw.get("sponsored_rank"), "cpc": round(cpc, 2) if cpc else None,
                     "status": status, "priority": round(priority)})
    kmap.sort(key=lambda r: r["priority"], reverse=True)

    focus = [k for k in kmap if k["status"] in {"push", "missing", "brand_defence_gap", "organic_top_unprotected"}
             and k["tier"] != "competitor"][:20]

    by_tier: dict[str, float] = defaultdict(float)
    for k in focus:
        if k["cpc"] and k["volume"]:
            by_tier[k["tier"]] += k["volume"] * CLICKS_PER_SEARCH["mid"] * TARGET_SPONSORED_SOV[k["tier"]] * k["cpc"]
    by_ad_type: dict[str, float] = defaultdict(float)
    for tier, spend in by_tier.items():
        for ad_type, share in AD_TYPE_SPLIT[tier].items():
            by_ad_type[ad_type] += spend * share

    repeat = _repeat_signals(products)
    retention_share = 0.15 if repeat["likelihood"] == "high" else 0.10
    subtotal = sum(by_tier.values())
    if subtotal:
        by_ad_type["SD (remarketing/retention)"] = subtotal * retention_share / (1 - retention_share)

    tiers_summary = defaultdict(lambda: {"keywords": 0, "volume": 0, "gaps": 0})
    for k in kmap:
        t = tiers_summary[k["tier"]]
        t["keywords"] += 1
        t["volume"] += k["volume"] or 0
        t["gaps"] += k["status"] in {"push", "missing", "brand_defence_gap"}

    return {
        "keyword_map": kmap[:150],
        "tiers": dict(tiers_summary),
        "focus_keywords": focus,
        "budget": {
            "monthly_by_tier": {k: round(v) for k, v in by_tier.items()},
            "monthly_by_ad_type": {k: round(v) for k, v in by_ad_type.items()},
            "monthly_total": round(sum(by_ad_type.values())),
            "assumptions": {"clicks_per_search": CLICKS_PER_SEARCH["mid"], "target_sponsored_sov": TARGET_SPONSORED_SOV,
                            "ad_type_split": AD_TYPE_SPLIT, "retention_share": retention_share},
        },
        "repeat_signals": repeat,
    }


def _repeat_signals(products: list[dict]) -> dict:
    if not products:
        return {"likelihood": "unknown"}
    sns = sum(1 for p in products if p.get("is_sns")) / len(products)
    multipack = sum(1 for p in products if MULTIPACK.search(p.get("title") or "")) / len(products)
    cats = " ".join(" ".join(p.get("category_path") or []) for p in products[:30])
    consumable = bool(CONSUMABLE_CATEGORIES.search(cats))
    score = (sns > 0.2) + (multipack > 0.15) + consumable
    return {"sns_share": round(sns, 2), "multipack_share": round(multipack, 2), "consumable_category": consumable,
            "likelihood": ["low", "medium", "high", "high"][score]}


def _observed_ads(keywords: list[dict], sov: list[dict], brand: str, bids: dict) -> dict:
    """What we can see of their advertising from outside, plus a rough spend range."""
    top = keywords[:30]
    sponsored = [k for k in top if k.get("sponsored_rank")]
    sov_by_kw = {s["keyword"]: s for s in sov}
    low = high = 0.0
    for s in sov:
        mine = [b for b in s["brands"] if _has_brand(b["brand"], brand)]
        cpc = _cpc({"keyword": s["keyword"]}, bids, sov_by_kw)
        if mine and s.get("volume_30d") and cpc:
            share = _frac(mine[0]["sponsored_sov"])
            low += s["volume_30d"] * share * CLICKS_PER_SEARCH["low"] * cpc
            high += s["volume_30d"] * share * CLICKS_PER_SEARCH["high"] * cpc
    return {
        "top30_keywords_with_sponsored_rank": len(sponsored),
        "top30_keywords": len(top),
        "sponsored_coverage": round(len(sponsored) / len(top), 2) if top else None,
        "est_monthly_spend_on_sampled_terms": {"low": round(low), "high": round(high)} if high else None,
        "note": "Estimate from share of voice x search volume x assumed ad click rate x CPC benchmark on sampled terms only.",
    }


def _amc_benchmark(products: list[dict]) -> dict | None:
    cats = [p.get("root_category") for p in products if p.get("root_category")]
    if not cats:
        return None
    top_cat = max(set(cats), key=cats.count)
    slug = re.sub(r"[^a-z0-9]+", "-", top_cat.lower()).strip("-")
    path = ROOT / "benchmarks" / f"amc_{slug}.json"
    bench = read_json(path)
    return bench or {"category": top_cat, "available": False}


def _previous_sov(run: Path) -> list[dict] | None:
    prefix = run.name.rsplit("-", 3)[0]
    older = sorted(d for d in RUNS_DIR.glob(f"{prefix}-*") if d.is_dir() and d.name < run.name)
    for d in reversed(older):
        prev = read_json(d / "js_sov.json")
        if prev:
            return prev
    return None


def build(run: Path) -> dict:
    target = read_json(run / "input.json", {})
    mp = MARKETPLACES[target.get("marketplace", "us")]
    kp = read_json(run / "keepa_products.json", {"discovered": 0, "products": []})
    products = kp["products"]
    brand = target.get("brand") or ""
    catalog = read_json(run / "js_catalog.json") or catalog_from_keepa(products)
    our_asins = {p["asin"] for p in catalog} | {p["asin"] for p in products} | set(target.get("seed_asins") or [])
    js_sales = read_json(run / "js_sales.json", {})
    keywords = read_json(run / "keywords.json", [])
    per_asin_kw = read_json(run / "keywords_by_asin.json", {})
    sov = read_json(run / "js_sov.json", [])
    serps = read_json(run / "serps.json", {})
    bids = read_json(run / "ads_bids.json", {})

    seeds = target.get("seed_asins") or []
    if target.get("scope") == "asin" and seeds:
        focus = checks.focus_on_asin(catalog, seeds[0], next((p for p in products if p["asin"] == seeds[0]), None))
    else:
        focus = checks.select_heroes(catalog)
    run_dir_name = run
    top = [h["asin"] for h in focus["heroes"]] or list(js_sales) or top_parents(products, 10)

    competitors = _competitors(sov, serps, brand, our_asins, _previous_sov(run))
    competitor_names = {r["brand"].lower() for r in competitors["share_of_voice"]
                        if r["brand"] and not r["is_prospect"] and len(r["brand"]) >= 3}
    attacked = {a["keyword"] for a in competitors["brand_term_attackers"]}
    strategy = _strategy(keywords, sov, bids, brand, competitor_names, attacked, products)

    return {
        "prospect": {"brand": target.get("brand"), "marketplace": target.get("marketplace"), "domain": mp["domain"],
                     "currency": mp["currency"], "input": target.get("input"), "seller_name": target.get("seller_name"),
                     "landing_asin": (target.get("seed_asins") or [None])[0]},
        "generated": dt.date.today().isoformat(),
        "coverage": read_json(run / "collect_log.json", {}),
        "focus": {k: v for k, v in focus.items() if k != "heroes"},
        "heroes": _with_sheets(_heroes(focus["heroes"], catalog, products, per_asin_kw, brand, competitor_names,
                                      attacked, bids, sov, keep_lead=focus.get("scope") == "asin"), run_dir_name),
        "quick_wins": _quick_wins(catalog, brand),
        "asin_map": _asin_map(products, kp["discovered"]),
        "catalogue": _catalogue(products, js_sales, top),
        "content": _content(products, top, read_json(run / "catalog.json", [])),
        "ads_observed": _observed_ads(keywords, sov, brand, bids),
        "competitors": competitors,
        "strategy": strategy,
        "amc_benchmark": _amc_benchmark(products),
        "job_ad_present": (run / "job_ad.txt").exists(),
    }


def catalog_from_keepa(products: list[dict]) -> list[dict]:
    """Fallback catalogue when Jungle Scout isn't available: Keepa's 'bought in past month' as units."""
    return [{"asin": p["asin"], "parent_asin": p.get("parent_asin") or p["asin"], "title": p.get("title"),
             "brand": p.get("brand"), "category": p.get("root_category"), "price": p.get("price"),
             "units_30d": p.get("monthly_sold"), "revenue_30d": (p.get("monthly_sold") or 0) * (p.get("price") or 0),
             "sellers": p.get("offer_count"), "available": p.get("price") is not None,
             "rating": p.get("rating"), "reviews": p.get("review_count"), "source": "keepa"} for p in products]


def _heroes(heroes: list[dict], catalog: list[dict], products: list[dict], per_asin_kw: dict, brand: str,
            competitor_names: set[str], attacked: set[str], bids: dict, sov: list[dict],
            keep_lead: bool = False) -> list[dict]:
    by_asin = {p["asin"]: p for p in catalog}
    keepa_by_asin = {p["asin"]: p for p in products}
    fams = checks.families(catalog)
    sov_by_kw = {s["keyword"]: s for s in sov}
    out = []
    brand_seller = checks.brand_seller([p.get("buy_box_owner") for p in catalog if checks.is_live(p)])
    for h in heroes:
        family_asins = [h["asin"], *h["children"]]
        h = h if keep_lead else {**h, "asin": _live_lead(h, keepa_by_asin)}
        js, kp = by_asin.get(h["asin"], {}), keepa_by_asin.get(h["asin"], {})
        p = {**js, **{k: v for k, v in kp.items() if v not in (None, [], "")}}
        p["price"] = js.get("price") or kp.get("price")
        p["rating"] = kp.get("rating") or js.get("rating")
        p["review_count"] = kp.get("review_count") or js.get("reviews")
        title = p.get("title") or ""
        leaf = (kp.get("category_path") or [None])[-1] or js.get("category")
        flags = []
        if mm := checks.category_mismatch(title, leaf):
            flags.append({"type": "wrong_category", "detail": f"{mm['product_type']} listed under {mm['category']}"})
        if mixed := checks.mixed_family(fams.get(h["parent_asin"], [])):
            flags.append({"type": "mixed_variation_family", "detail": "variation family mixes " + ", ".join(mixed)})
        flags += [{"type": "sellers", "detail": d} for d in checks.seller_flags(p, brand, brand_seller)]
        if s := checks.stock_flag(p):
            flags.append({"type": "stock", "detail": s})
        if s := checks.price_flag(p):
            flags.append({"type": "price", "detail": s})

        # keywords were pulled for one variant with include_variants, so they describe the family
        kws = merge_keywords([r for a in family_asins for r in per_asin_kw.get(a, [])])
        # judge relevance against every title in the family: variants often word the same product differently
        family_text = " ".join(filter(None, [title] + [by_asin.get(a, {}).get("title") for a in family_asins]
                                      + [keepa_by_asin.get(a, {}).get("title") for a in family_asins]))
        wasted = checks.wasted_terms(family_text, brand, kws, competitor_names)
        wasted_set = {w["keyword"] for w in wasted}
        targets = []
        title_stems = checks.stems(family_text) - checks.stems(brand)
        for kw in kws:
            # skip wasted terms, and terms that belong to a sibling in the family (e.g. "face oil" on a balm)
            if kw["keyword"] in wasted_set or not (checks.stems(kw["keyword"]) & title_stems):
                continue
            tier = _tier(kw, brand, competitor_names, None)
            status = _status(kw)
            if tier == "brand" and kw["keyword"] in attacked and status in {"organic_top_unprotected", "missing"}:
                status = "brand_defence_gap"
            if status in {"push", "brand_defence_gap", "organic_top_unprotected"} and tier != "competitor":
                cpc = _cpc(kw, bids, sov_by_kw)
                targets.append({"keyword": kw["keyword"], "tier": tier, "status": status, "volume": kw.get("volume"),
                                "organic_rank": kw.get("organic_rank"), "sponsored_rank": kw.get("sponsored_rank"),
                                "cpc": round(cpc, 2) if cpc else None})
        targets.sort(key=lambda t: t["volume"] or 0, reverse=True)
        out.append({
            "asin": h["asin"], "parent_asin": h["parent_asin"], "title": title,
            "family_revenue_30d": h["revenue_30d"], "family_size": len(h["children"]),
            "family_revenue_keepa": _keepa_revenue(family_asins, keepa_by_asin),
            "units_30d": p.get("units_30d") or p.get("monthly_sold"), "price": p.get("price"),
            "list_price": p.get("list_price"), "sellers": p.get("sellers") or p.get("offer_count"),
            "buy_box_owner": p.get("buy_box_owner"),
            "sold_by": "Amazon" if checks.sold_by_amazon(p) else p.get("buy_box_owner"), "category": leaf, "product_type": checks.product_type(title),
            "rating": p.get("rating"), "reviews": p.get("reviews") or p.get("review_count"),
            "sales_rank": kp.get("sales_rank"),
            "content": check_listing(p) if kp else None,
            "mobile": mobile.check(p, brand) if kp else None,
            "flags": flags, "targets": targets[:6], "wasted_terms": wasted[:8],
            "sponsored_terms": sum(1 for k in kws if k.get("sponsored_rank")),
        })
    return out


def _with_sheets(heroes: list[dict], run: Path) -> list[dict]:
    """Point each best-seller at its phone-size image sheet, if the images step made one."""
    for h in heroes:
        sheet = run / "mobile" / f"{h['asin']}.png"
        h["mobile_sheet"] = str(sheet.relative_to(run)) if sheet.exists() else None
    return heroes


def _keepa_revenue(asins: list[str], keepa_by_asin: dict) -> int | None:
    """Cross-check from Keepa's 'bought in past month' (a lower bound) x current price, per variant."""
    total = sum((k.get("monthly_sold") or 0) * (k.get("price") or 0)
                for k in (keepa_by_asin.get(a) for a in dict.fromkeys(asins)) if k)
    return round(total) or None


def _live_lead(hero: dict, keepa_by_asin: dict) -> str:
    """Jungle Scout repeats family sales on every child, so it can't say which variant really sells.
    Prefer a child Keepa sees with a live offer: most bought last month, then best sales rank."""
    live = [keepa_by_asin[a] for a in hero["children"] if a in keepa_by_asin and keepa_by_asin[a].get("price")]
    if not live:
        return hero["asin"]
    return max(live, key=lambda k: (k.get("monthly_sold") or 0, -(k.get("sales_rank") or 1e9)))["asin"]


def _quick_wins(catalog: list[dict], brand: str) -> dict:
    live = [p for p in catalog if checks.is_live(p)]
    mixed = []
    for parent, kids in checks.families(live).items():
        if types := checks.mixed_family(kids):
            mixed.append({"parent_asin": parent, "product_types": types, "children": [k["asin"] for k in kids]})
    return {"duplicates": checks.duplicates(live, brand), "clutter": checks.clutter(live, brand),
            "mixed_families": mixed}
```

### `analyse/checks.py`

```python
"""Catalogue focus (the 80/20 best-sellers) and the checks that matter for them.

Rules from reviewing real audits:
- Only live ASINs with real sales count. Dead listings and tiny sellers are context, never findings.
- Long stockouts usually mean a discontinued line, so they're ignored. Only a live best-seller that
  keeps running out is a finding (lost sales).
- Wrong category, mixed variation families, duplicates and listing clutter are quick wins.
- Sponsored ranks on terms unrelated to the product point to wasted ad spend.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict

HERO_REVENUE_SHARE = 0.80
MAX_HERO_FAMILIES = 12
STOCKOUT_FLAG_RANGE = (10, 60)        # % of last 90 days; above 60 reads as discontinued
CROWDED_SELLERS = 5
DUPLICATE_SIMILARITY = 0.8

STOPWORDS = set("""a an and the for with of in on to by from at as is it this that your you our new
best pack set size ml g kg oz x pcs piece pieces count ct uk us edition""".split())
FOREIGN_WORDS = set("""und mit für fur der die das gesicht creme pflege avec pour le la les et sans
para con el los las y crema per il della""".split())

# Product types we can read from a title, and words a correct category leaf would contain.
# Extend for new verticals; anything unmatched is left to the skill's judgement.
PRODUCT_TYPES: list[tuple[str, tuple[str, ...]]] = [
    ("cleansing balm", ("cleans", "balm", "make-up remov", "makeup remov", "face wash")),
    ("cleansing oil", ("cleans", "oil", "make-up remov", "makeup remov", "face wash")),
    ("micellar water", ("cleans", "micellar", "make-up remov", "makeup remov")),
    ("cleanser", ("cleans", "face wash", "wash")),
    ("face wash", ("cleans", "face wash", "wash")),
    ("scrub", ("scrub", "exfoliat", "polish")),
    ("exfoliator", ("scrub", "exfoliat", "peel")),
    ("toner", ("toner", "tonic", "mist")),
    ("serum", ("serum", "treatment", "oil")),
    ("eye cream", ("eye",)),
    ("night cream", ("night", "moistur", "cream")),
    ("day cream", ("day", "moistur", "cream")),
    ("moisturiser", ("moistur", "cream", "lotion")),
    ("moisturizer", ("moistur", "cream", "lotion")),
    ("facial oil", ("oil", "serum", "moistur")),
    ("face mask", ("mask",)),
    ("sheet mask", ("mask",)),
    ("sunscreen", ("sun", "spf")),
    ("primer", ("primer", "foundation", "base")),
    ("foundation", ("foundation",)),
    ("lip balm", ("lip",)),
    ("shampoo", ("shampoo",)),
    ("conditioner", ("conditioner",)),
    ("body lotion", ("body", "lotion", "moistur")),
    ("body wash", ("body", "wash", "shower")),
    ("deodorant", ("deodorant", "antiperspirant")),
    ("supplement", ("supplement", "vitamin", "capsule", "tablet")),
]


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def tokens(s: str | None) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) > 2 and t not in STOPWORDS}


def stems(s: str | None) -> set[str]:
    """Crude stemming so 'cleansing' matches 'cleanser' and 'facial' matches 'facials'."""
    return {t[:5] for t in tokens(s)}


def product_type(title: str | None) -> str | None:
    t = (title or "").lower()
    for name, _ in PRODUCT_TYPES:
        if name in t:
            return name
    return None


def is_live(p: dict) -> bool:
    if p.get("available") is False or (p.get("sellers") == 0):
        return False
    return bool(p.get("price")) and bool((p.get("units_30d") or 0) > 0 or (p.get("revenue_30d") or 0) > 0)


# --- 80/20 ------------------------------------------------------------------------------------

def families(products: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for p in products:
        out[p.get("parent_asin") or p["asin"]].append(p)
    return out


def family_revenue(children: list[dict]) -> float:
    """Jungle Scout often repeats the parent's totals on every child: the same revenue, or the same
    units at each child's own price. Count the family once when it does."""
    revs = [c.get("revenue_30d") or 0 for c in children]
    units = [c.get("units_30d") or 0 for c in children]
    prices = [c.get("price") for c in children if c.get("price")]
    if len(children) > 1 and len(set(revs)) == 1:
        return revs[0]
    near_same_units = min(units) > 0 and max(units) <= min(units) * 1.15
    nz = sorted(u for u in units if u)
    repeated_units = any(b - a <= 0.02 * b for a, b in zip(nz, nz[1:]))  # two variants within 2%: copied total
    if len(children) > 1 and (near_same_units or repeated_units) and prices:
        # Family-level units copied onto each pack size: price them at the single-unit price, otherwise a
        # 6-pack at 6x the price looks like 6x the revenue (conservative by design).
        return max(units) * min(prices)
    return sum(revs)


def select_heroes(products: list[dict], share: float = HERO_REVENUE_SHARE,
                  max_families: int = MAX_HERO_FAMILIES) -> dict:
    live = [p for p in products if is_live(p)]
    fams = families(live)
    ranked = sorted(((parent, family_revenue(kids), kids) for parent, kids in fams.items()),
                    key=lambda r: r[1], reverse=True)
    total = sum(r[1] for r in ranked)
    heroes, covered = [], 0.0
    for parent, rev, kids in ranked:
        if total and covered / total >= share or len(heroes) >= max_families or rev <= 0:
            break
        lead = max(kids, key=lambda k: (k.get("units_30d") or 0, k.get("reviews") or 0))
        heroes.append({"parent_asin": parent, "asin": lead["asin"], "revenue_30d": round(rev),
                       "children": [k["asin"] for k in kids]})
        covered += rev
    return {
        "total_asins": len(products),
        "live_asins": len(live),
        "families": len(fams),
        "hero_families": len(heroes),
        "hero_revenue_share": round(covered / total, 2) if total else None,
        "est_monthly_revenue": round(total) if total else None,
        "heroes": heroes,
    }


def focus_on_asin(catalog: list[dict], seed: str, seed_product: dict | None = None) -> dict:
    """Single-product audit: the seed's variation family is the only 'best-seller', with the seed as lead.
    Brand totals are kept for context only."""
    row = next((r for r in catalog if r["asin"] == seed), None)
    parent = (row or {}).get("parent_asin") or (seed_product or {}).get("parent_asin") or seed
    kids = [r for r in catalog if (r.get("parent_asin") or r["asin"]) == parent] or ([row] if row else [])
    if not kids and seed_product:  # Jungle Scout doesn't know it: fall back to Keepa's bought-last-month
        units = seed_product.get("monthly_sold") or 0
        kids = [{"asin": seed, "parent_asin": parent, "price": seed_product.get("price"), "units_30d": units,
                 "revenue_30d": units * (seed_product.get("price") or 0)}]
    live = [r for r in catalog if is_live(r)]
    brand_total = sum(family_revenue(k) for k in families(live).values())
    rev = family_revenue(kids) if kids else 0
    return {
        "scope": "asin",
        "seed": seed,
        "total_asins": len(catalog),
        "live_asins": len(live),
        "families": len(families(live)),
        "hero_families": 1,
        "hero_revenue_share": round(rev / brand_total, 2) if brand_total else None,
        "est_monthly_revenue": round(rev) if rev else None,
        "brand_monthly_revenue": round(brand_total) if brand_total else None,
        "heroes": [{"parent_asin": parent, "asin": seed, "revenue_30d": round(rev),
                    "children": list(dict.fromkeys([seed, *(k["asin"] for k in kids)]))}],
    }


# --- per-hero checks --------------------------------------------------------------------------

def category_mismatch(title: str, category_leaf: str | None) -> dict | None:
    ptype = product_type(title)
    if not ptype or not category_leaf:
        return None
    expected = dict(PRODUCT_TYPES)[ptype]
    leaf = category_leaf.lower()
    if any(word in leaf for word in expected):
        return None
    return {"product_type": ptype, "category": category_leaf}


def mixed_family(children: list[dict]) -> list[str] | None:
    """A variation family whose children are different products (e.g. balm + scrub + night cream)."""
    types = sorted({t for t in (product_type(c.get("title")) for c in children) if t})
    return types if len(types) > 1 else None


def brand_seller(owners: list[str | None]) -> str | None:
    """The brand's own seller account: the non-Amazon seller holding the most Buy Boxes, when it holds 80%+
    of the range or at least 3x as many as the next seller (e.g. Warpaint Cosmetics for W7: 72 vs 16)."""
    counts: dict[str, int] = defaultdict(int)
    for o in owners:
        if o and "amazon" not in o.lower():
            counts[o] += 1
    if not counts:
        return None
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top, n = ranked[0]
    total = sum(1 for o in owners if o)
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    return top if (total and n / total >= 0.8) or n >= 3 * max(runner_up, 1) else None


def sold_by_amazon(p: dict) -> bool:
    return "amazon" in (p.get("buy_box_owner") or "").lower()


def seller_flags(p: dict, brand: str, brand_seller: str | None = None) -> list[str]:
    """Reseller problems only exist when a third party holds the Buy Box. When Amazon sells it (Vendor/1P),
    Amazon sets the price and other offers aren't winning sales, so there's nothing to pitch."""
    if sold_by_amazon(p):
        return []
    flags = []
    owner = p.get("buy_box_owner") or ""
    if owner and owner != brand_seller and "amazon" not in owner.lower() and norm(brand)[:6] not in norm(owner):
        flags.append(f"Buy Box held by {owner}")
    sellers = p.get("sellers") or p.get("offer_count")
    if sellers and sellers >= CROWDED_SELLERS:
        flags.append(f"{sellers} sellers on the listing")
    if p.get("price") and p.get("list_price") and p["price"] > p["list_price"] * 1.05:
        flags.append(f"selling above list price ({p['price']:.2f} vs {p['list_price']:.2f})")
    return flags


def stock_flag(p: dict) -> str | None:
    listed = p.get("listed_since")
    if listed and (dt.date.today() - dt.date.fromisoformat(listed)).days < 180:
        return None  # new or seasonal listings often go live before stock lands
    oos = p.get("oos_pct_90")
    lo, hi = STOCKOUT_FLAG_RANGE
    if oos is not None and lo <= oos <= hi:
        return f"out of stock {oos}% of the last 90 days"
    return None


def price_flag(p: dict) -> str | None:
    if sold_by_amazon(p):
        return None  # Amazon's retail price, not the brand's or a reseller's
    if p.get("price") and p.get("list_price") and p["price"] < p["list_price"] * 0.7:
        return f"discounted {100 - 100 * p['price'] / p['list_price']:.0f}% off list ({p['price']:.2f} vs {p['list_price']:.2f})"
    return None


# --- quick wins across live listings ----------------------------------------------------------

def _core_tokens(title: str, brand: str) -> set[str]:
    brand_toks = tokens(brand) | {norm(brand)}
    return {t for t in tokens(title) if t not in brand_toks and not re.fullmatch(r"\d+(ml|g|oz)?", t)}


def duplicates(live: list[dict], brand: str) -> list[list[dict]]:
    """Separate listings (different parents) for what reads as the same product."""
    groups: list[list[dict]] = []
    seen: set[str] = set()
    for i, a in enumerate(live):
        if a["asin"] in seen:
            continue
        ta, group = _core_tokens(a.get("title", ""), brand), [a]
        for b in live[i + 1:]:
            if b["asin"] in seen or (b.get("parent_asin") or b["asin"]) == (a.get("parent_asin") or a["asin"]):
                continue
            tb = _core_tokens(b.get("title", ""), brand)
            if ta and tb and len(ta & tb) / len(ta | tb) >= DUPLICATE_SIMILARITY:
                group.append(b)
        if len(group) > 1:
            seen.update(p["asin"] for p in group)
            groups.append([{"asin": p["asin"], "title": (p.get("title") or "")[:80],
                            "revenue_30d": p.get("revenue_30d")} for p in group])
    return groups


def clutter(live: list[dict], brand: str) -> list[dict]:
    b = norm(brand)
    spaced = (brand or "").lower()
    out = []
    for p in live:
        title = p.get("title") or ""
        issue = None
        if norm(title) == b:
            issue = "title is just the brand name"
        elif len(tokens(title) & FOREIGN_WORDS) >= 2:
            issue = "title not in the marketplace language"
        elif b and b not in norm(title):
            issue = "brand name missing from title"
        elif spaced and " " in spaced and spaced not in title.lower():
            issue = "brand name spelled inconsistently"
        if issue:
            out.append({"asin": p["asin"], "title": title[:80], "issue": issue})
    return out


# --- ads --------------------------------------------------------------------------------------

# Words that refine a search without changing what product it's for
GENERIC_MODIFIERS = set("""best cheap gift gifts set sets new for women woman womens ladies her him adult adults uk
2024 2025 2026 2027 christmas xmas present presents luxury large small mini travel pack edition the and with
calendar calendars""".split())


def _relevant(keyword: str, title_text: str, title_stems: set[str]) -> bool:
    kt = tokens(keyword)
    if stems(keyword) & title_stems:
        return True
    words = re.findall(r"[a-z0-9]+", keyword.lower())  # "make up" vs "makeup"
    return any((a + b) in norm(title_text) for a, b in zip(words, words[1:]))


def _off_target(keyword: str, title_text: str, title_stems: set[str], ranked_vocab: set[str]) -> str | None:
    """A qualifier that makes it a different product: 'squishy advent calendar' on a makeup calendar.
    Words from searches the product already ranks on page one for (top 20) are treated as relevant."""
    for t in tokens(keyword):
        if (t in GENERIC_MODIFIERS or t[:5] in title_stems or t in norm(title_text)
                or t[:5] in ranked_vocab):
            continue
        return t
    return None


def wasted_terms(hero_title: str, brand: str, keywords: list[dict],
                 competitor_names: set[str] | None = None) -> list[dict]:
    """Terms the hero is sponsored on but has no organic relevance to: auto/broad drift."""
    title_stems = stems(hero_title) - stems(brand)  # "facialist" must not make "facial oil" relevant
    brand_toks = tokens(brand)
    ranked_vocab = {t[:5] for k in keywords if 0 < (k.get("organic_rank") or 0) <= 20 for t in tokens(k["keyword"])}
    rivals = {t for n in (competitor_names or set()) for t in tokens(n)}
    out = []
    for k in keywords:
        if not k.get("sponsored_rank"):
            continue
        nk, nb = norm(k["keyword"]), norm(brand)
        if nb and nb in nk:
            continue  # own-brand searches (any spelling, any product) are brand defence, never waste
        organic = k.get("organic_rank") or 999   # Jungle Scout uses 0 for "not ranked"
        qualifier = _off_target(k["keyword"], hero_title, title_stems, ranked_vocab) if organic > 50 else None
        if qualifier:
            rival = qualifier in rivals
            out.append({"keyword": k["keyword"], "volume": k.get("volume"), "sponsored_rank": k["sponsored_rank"],
                        "reason": "competitor's brand: worth reviewing" if rival else f'different product ("{qualifier}")'})
            continue
        if organic <= 100:
            continue
        kt = tokens(k["keyword"])
        partial_brand = bool(nk) and nk != nb and ((kt and kt <= brand_toks) or nb.startswith(nk))
        if partial_brand or not _relevant(k["keyword"], hero_title, title_stems):
            out.append({"keyword": k["keyword"], "volume": k.get("volume"), "sponsored_rank": k["sponsored_rank"],
                        "reason": "partial brand term" if partial_brand else "unrelated to the product"})
    return sorted(out, key=lambda r: r.get("volume") or 0, reverse=True)
```

### `analyse/mobile.py`

```python
"""Mobile-shopper checks for the best-sellers. Most Amazon traffic is the app or mobile web: images are
small, titles are cut short in search, bullets sit collapsed under "About this item" and A+ modules stack
full-width. Thresholds mirror .claude/skills/outreach/references/mobile-rubric.md; change both together.
"""
from __future__ import annotations

import html
import re

from . import checks
from .rubric import FAIL, GOOD, POINTS, WARN

ZOOM_MIN, ZOOM_GOOD = 1000, 1600        # px on the longest side; below 1000 Amazon disables zoom
MOBILE_TITLE_CHARS = 80                 # roughly what mobile search shows before truncating
LONG_BULLET = 250
HEAVY_TEXT_WORDS = 30                   # words of copy inside one A+ image
NON_BRAND_CREATORS = {"influencer", "customer", "creator", "user", "buyer"}
SIZE_RE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:ml|l|g|kg|oz|fl\s?oz|cm|mm|pack|pcs|pieces|count|ct|capsules|tablets|"
                     r"sachets|x)\b|\bpack of \d+|\b\d+\s?-?\s?pack\b", re.I)


def _zoom(images: list[dict]) -> tuple[str, str] | None:
    sizes = [max(i.get("w") or 0, i.get("h") or 0) for i in images if i.get("w") or i.get("h")]
    if not sizes:
        return None
    small = sum(1 for s in sizes if s < ZOOM_MIN)
    if small:
        return FAIL, f"{small} of {len(sizes)} images under {ZOOM_MIN}px, so they can't be zoomed"
    soft = sum(1 for s in sizes if s < ZOOM_GOOD)
    if soft:
        return WARN, f"all zoomable, but {soft} under {ZOOM_GOOD}px look soft when pinched"
    return GOOD, f"all {len(sizes)} images zoomable ({min(sizes)}px+)"


def _video(videos: list[dict]) -> tuple[str, str]:
    if not videos:
        return FAIL, "no video on the listing"
    brand = [v for v in videos if (v.get("creator") or "").strip().lower() not in NON_BRAND_CREATORS]
    if not brand:
        return WARN, f"{len(videos)} video(s), all influencer or customer: no brand-made video"
    if all(not v.get("duration") for v in brand):  # Keepa sometimes doesn't record the length
        return GOOD, f"{len(brand)} brand video(s) (length not recorded)"
    short = [v for v in brand if v.get("duration") and v["duration"] <= 90]
    if not short:
        return WARN, f"brand video is {min(v['duration'] for v in brand if v.get('duration'))}s; aim for 60s or less on mobile"
    return GOOD, f"{len(brand)} brand video(s), shortest {min(v.get('duration') or 0 for v in short)}s"


def _title(title: str, brand: str) -> tuple[str, str]:
    head = (title or "")[:MOBILE_TITLE_CHARS]
    missing = []
    if checks.norm(brand) and checks.norm(brand) not in checks.norm(head):
        missing.append("brand")
    full_type = checks.product_type(title)
    if full_type and full_type not in head.lower():
        missing.append("product type")
    if SIZE_RE.search(title or "") and not SIZE_RE.search(head):
        missing.append("size/pack")
    if not missing:
        return GOOD, f"first {MOBILE_TITLE_CHARS} characters carry brand, product and size"
    status = FAIL if "product type" in missing else WARN
    return status, f"cut off on mobile before the {', '.join(missing)}"


def _bullets(features: list[str] | None) -> tuple[str, str] | None:
    if features is None:
        return None
    if not features:
        return FAIL, "no bullets"
    long = sum(1 for f in features if len(f) > LONG_BULLET)
    first = features[0]
    if long:
        return WARN, f"{long} bullet(s) over {LONG_BULLET} characters; mobile shows these collapsed"
    return GOOD, f"{len(features)} bullets, first is {len(first)} characters"


def text_words(alt: str) -> int:
    """Amazon's A+ alt text quotes the copy inside the image: "Text reads 'x' and 'y'"."""
    quoted = re.findall(r"'([^']+)'", html.unescape(alt))
    return sum(len(q.split()) for q in quoted)


def _aplus(alts: list[str], has_aplus: bool) -> tuple[str, str] | None:
    if not has_aplus:
        return FAIL, "no A+ content"
    if not alts:
        return None
    heavy = sum(1 for a in alts if text_words(a) > HEAVY_TEXT_WORDS)
    if heavy >= 3:
        return FAIL, f"{heavy} of {len(alts)} A+ images are text-heavy, too small to read when stacked on a phone"
    if heavy:
        return WARN, f"{heavy} of {len(alts)} A+ images are text-heavy for a phone screen"
    return GOOD, f"{len(alts)} A+ images with light, phone-friendly text"


def check(p: dict, brand: str) -> dict:
    images = p.get("images_detail") or []
    results = {
        "zoom": _zoom(images),
        "image_count": (GOOD if len(images) >= 7 else WARN if len(images) >= 5 else FAIL,
                        f"{len(images)} gallery images") if images else None,
        "video": _video(p.get("videos_detail") or []) if "videos_detail" in p else None,
        "title_on_mobile": _title(p.get("title") or "", brand),
        "bullets_on_mobile": _bullets(p.get("features")),
        "a_plus_on_mobile": _aplus(p.get("aplus_alt") or [], bool(p.get("has_aplus"))) if "aplus_alt" in p else None,
    }
    known = {k: v for k, v in results.items() if v}
    score = round(100 * sum(POINTS[s] for s, _ in known.values()) / (2 * len(known))) if known else None
    return {"score": score, "checks": {k: {"status": s, "detail": d} for k, (s, d) in known.items()}}
```

### `analyse/rubric.py`

```python
"""Listing-quality checks. Thresholds mirror .claude/skills/outreach/references/scoring-rubric.md;
change both together."""
from __future__ import annotations

GOOD, WARN, FAIL = "good", "warn", "fail"
POINTS = {GOOD: 2, WARN: 1, FAIL: 0}


def _band(value, good_at: float, warn_at: float) -> str:
    if value is None:
        return WARN
    if value >= good_at:
        return GOOD
    return WARN if value >= warn_at else FAIL


def check_listing(p: dict) -> dict:
    title_len = p.get("title_len") or 0
    checks = {
        "images": (_band(p.get("image_count"), 7, 5), f"{p.get('image_count', 0)} images"),
        "video": (GOOD if p.get("video_count") else FAIL, f"{p.get('video_count', 0)} video{'' if p.get('video_count') == 1 else 's'}"),
        "a_plus": (GOOD if p.get("has_aplus") else FAIL,
                   f"A+ with {p.get('aplus_modules', 0)} modules" if p.get("has_aplus") else "no A+"),
        "title": (GOOD if 80 <= title_len <= 200 else WARN, f"{title_len} chars"),
        "bullets": (_band(p.get("bullet_count"), 5, 3),
                    f"{p['bullet_count']} bullets" if p.get("bullet_count") is not None else "bullets not captured"),
        "bullet_depth": (_band(p.get("bullet_avg_len"), 120, 70),
                         f"avg {p['bullet_avg_len']} chars" if p.get("bullet_avg_len") is not None else "not captured"),
        "rating": (_band(p.get("rating"), 4.3, 4.0), f"{p.get('rating') or '–'}★"),
        "reviews": (_band(p.get("review_count"), 100, 20), f"{p.get('review_count') or 0} reviews"),
    }
    score = sum(POINTS[s] for s, _ in checks.values()) / (2 * len(checks))
    return {
        "score": round(score * 100),
        "checks": {k: {"status": s, "detail": d} for k, (s, d) in checks.items()},
    }
```

### `analyse/render.py`

````python
"""Render audit.html + evidence.md from dataset.json and the skill-written findings.json.

    python -m analyse.render runs/<slug>

Layout and styling live in .claude/skills/outreach/templates/audit.html; this fills its slots.
Charts are inline SVG with <title> tooltips; every chart has a table beside or below it.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

from collectors.common import ROOT, read_json

TEMPLATE = ROOT / ".claude/skills/outreach/templates/audit.html"
STATUS_ICON = {"good": ("✓", "Good"), "warn": ("!", "Needs work"), "fail": ("✕", "Missing")}
KW_STATUS = {
    "push": "Ranks page 1–2, no ads: push to top",
    "missing": "Not visible",
    "brand_defence_gap": "Competitors bidding, brand not defended",
    "organic_top_unprotected": "Top organically, no ad cover",
    "sponsored_only": "Paid only, weak organic",
    "sponsored_support": "Ads supporting organic",
    "own": "Owns the top of page",
}
MOBILE_LABEL = {"zoom": "Zoom", "image_count": "Images", "video": "Video", "title_on_mobile": "Title in search",
                "bullets_on_mobile": "Bullets", "a_plus_on_mobile": "A+ on a phone"}
TIER_LABEL = {"brand": "Brand", "core": "Core", "category": "Category", "long_tail": "Long-tail", "competitor": "Competitor"}


def e(v) -> str:
    return html.escape("" if v is None else str(v))


def money(v, cur: str) -> str:
    if v is None:
        return "–"
    return f"{cur}{v:,.0f}" if v >= 100 else f"{cur}{v:,.2f}"


def pct(v) -> str:
    return "–" if v is None else f"{v * 100:.0f}%"


def num(v) -> str:
    return "–" if v is None else f"{v:,.0f}"


# --- charts --------------------------------------------------------------------------------------

def hbars(rows: list[tuple[str, float, bool]], fmt=pct) -> str:
    """Horizontal bars for share of voice. Highlighted row = the prospect."""
    if not rows:
        return '<p class="empty">No share-of-voice data.</p>'
    top = max(v for _, v, _ in rows) or 1
    out = ['<div class="hbars">']
    for label, v, mine in rows:
        out.append(f'<div class="hbar{" mine" if mine else ""}"><span class="hbar-label">{e(label)}</span>'
                   f'<span class="hbar-track"><span class="hbar-fill" style="width:{100 * v / top:.1f}%" title="{e(label)}: {e(fmt(v))}"></span></span>'
                   f'<span class="hbar-value">{e(fmt(v))}</span></div>')
    out.append("</div>")
    return "".join(out)


def stacked(parts: dict[str, float], cur: str) -> str:
    total = sum(parts.values())
    if not total:
        return '<p class="empty">Not enough keyword and CPC data to size a budget.</p>'
    segs = "".join(f'<span class="seg s{i}" style="flex:{v}" title="{e(k)}: {e(money(v, cur))}"></span>'
                   for i, (k, v) in enumerate(parts.items()))
    legend = "".join(f'<li><span class="sw s{i}"></span>{e(k)} <b>{e(money(v, cur))}</b> <small>{v / total:.0%}</small></li>'
                     for i, (k, v) in enumerate(parts.items()))
    return f'<div class="stack">{segs}</div><ul class="legend">{legend}</ul>'


# --- sections ------------------------------------------------------------------------------------

def points_html(findings: dict) -> str:
    out = []
    for p in findings.get("points", [])[:5]:
        quote = f'<p class="quote">You asked for: “{e(p["job_ad_quote"])}”</p>' if p.get("job_ad_quote") else ""
        evidence = "".join(f"<li>{e(x)}</li>" for x in p.get("evidence", []))
        out.append(f'<li class="point"><div class="point-body"><span class="tag">{e(p.get("category", ""))}</span>'
                   f'<h3>{e(p["title"])}</h3><p>{e(p["detail"])}</p>{quote}'
                   f'<details><summary>What we saw</summary><ul>{evidence}</ul></details></div></li>')
    return "".join(out)


def stats_html(d: dict) -> str:
    cur = d["prospect"]["currency"]
    f, ads = d.get("focus") or {}, d["ads_observed"]
    if f.get("scope") == "asin" and d.get("heroes"):
        h = d["heroes"][0]
        tiles = [
            ("Est. monthly revenue", money(f.get("est_monthly_revenue"), cur), "this product family, Jungle Scout 30-day"),
            ("Sales rank", f'#{num(h.get("sales_rank"))}' if h.get("sales_rank") else "–", "in its main category (Keepa)"),
            ("Rating", f'{h.get("rating") or "–"}★', f'{num(h.get("reviews"))} reviews'),
            ("Sponsored coverage", pct(ads["sponsored_coverage"]), "of its top 30 keywords"),
        ]
        return "".join(f'<div class="stat"><span class="stat-label">{e(a)}</span><span class="stat-value">{e(b)}</span>'
                       f'<span class="stat-note">{e(c)}</span></div>' for a, b, c in tiles)
    tiles = [
        ("ASINs listed", num(f.get("total_asins")), f'{num(f.get("live_asins"))} live and selling'),
        ("Best-sellers", num(f.get("hero_families")), f'product families making {pct(f.get("hero_revenue_share"))} of revenue'),
        ("Est. monthly revenue", money(f.get("est_monthly_revenue"), cur), "Jungle Scout 30-day estimate"),
        ("Sponsored coverage", pct(ads["sponsored_coverage"]), "of their top 30 keywords"),
    ]
    scores = [h["mobile"]["score"] for h in d.get("heroes", []) if h.get("mobile") and h["mobile"].get("score") is not None]
    if scores:
        ready = sum(1 for s in scores if s >= 75)
        tiles.append(("Mobile-ready best-sellers", f"{ready} of {len(scores)}", "zoom, video, title, bullets and A+ on a phone"))
    return "".join(f'<div class="stat"><span class="stat-label">{e(a)}</span><span class="stat-value">{e(b)}</span>'
                   f'<span class="stat-note">{e(c)}</span></div>' for a, b, c in tiles)


def heroes_html(d: dict, findings: dict) -> str:
    """One card per best-seller: what it earns, what's wrong, what to do."""
    cur, domain = d["prospect"]["currency"], d["prospect"]["domain"]
    actions = findings.get("hero_actions") or {}
    cards = []
    for h in d.get("heroes", []):
        flags = "".join(f'<li><span class="chip warn" title="Issue">!</span> {e(fl["detail"])}</li>' for fl in h["flags"])
        targets = "".join(
            f'<li>“{e(t["keyword"])}” <small>{num(t["volume"])}/mo · organic #{e(t["organic_rank"] or "–")}'
            f'{" · " + money(t["cpc"], cur) + " CPC" if t["cpc"] else ""}</small></li>' for t in h["targets"][:3])
        wasted = ", ".join(f'“{e(w["keyword"])}”' for w in h["wasted_terms"][:5])
        action = f'<p class="action">{e(actions[h["asin"]])}</p>' if actions.get(h["asin"]) else ""
        mob = h.get("mobile") or {}
        review = (findings.get("mobile_review") or {}).get(h["asin"]) or {}
        mobile_items = "".join(
            f'<li><span class="chip {c["status"]}" title="{e(STATUS_ICON[c["status"]][1])}">{STATUS_ICON[c["status"]][0]}</span> '
            f'{e(MOBILE_LABEL.get(k, k))}: {e(c["detail"])}</li>' for k, c in (mob.get("checks") or {}).items())
        if review.get("verdict"):
            mobile_items += f'<li class="verdict">{e(review["verdict"])}</li>'
        mobile_html = (f'<div><h4>Mobile{" · " + str(mob["score"]) + "/100" if mob.get("score") is not None else ""}</h4>'
                       f'<ul class="flags">{mobile_items}</ul></div>') if mobile_items else ""
        meta = " · ".join(x for x in (
            f'{money(h["family_revenue_30d"], cur)}/mo' if h.get("family_revenue_30d") else "",
            f'{num(h["units_30d"])} units' if h.get("units_30d") else "",
            money(h["price"], cur) if h.get("price") else "",
            f'{h["rating"]}★ ({num(h["reviews"])})' if h.get("rating") else "") if x)
        cards.append(
            f'<article class="hero-card"><header><a href="https://www.{e(domain)}/dp/{e(h["asin"])}">{e(h["asin"])}</a>'
            f'<h3>{e((h["title"] or "")[:90])}</h3><span class="hero-meta">{e(meta)}</span></header>{action}'
            + (f'<div><h4>Fix</h4><ul class="flags">{flags}</ul></div>' if flags else "")
            + (f'<div><h4>Push</h4><ul>{targets}</ul></div>' if targets else "")
            + (f'<div><h4>Cut</h4><p>{wasted}</p></div>' if wasted else "")
            + mobile_html
            + "</article>")
    return "".join(cards) or '<p class="empty">No best-seller data in this run.</p>'


def quick_wins_html(d: dict) -> str:
    q = d.get("quick_wins") or {}
    items = []
    for group in q.get("duplicates", [])[:6]:
        items.append("Duplicate listings: " + " / ".join(f'{e(g["asin"])}' for g in group)
                     + f' <small>{e(group[0]["title"])}</small>')
    for m in q.get("mixed_families", [])[:3]:
        items.append(f'Variation family {e(m["parent_asin"])} mixes {e(", ".join(m["product_types"]))}')
    for c in q.get("clutter", [])[:6]:
        items.append(f'{e(c["asin"])}: {e(c["issue"])} <small>{e(c["title"])}</small>')
    return f'<ul class="quick">{"".join(f"<li>{i}</li>" for i in items)}</ul>' if items else \
        '<p class="empty">No duplicate or untidy listings found among live products.</p>'


def content_table(d: dict) -> str:
    checks = ["images", "video", "a_plus", "title", "bullets", "bullet_depth", "rating", "reviews"]
    head = "".join(f"<th>{c.replace('_', ' ').title()}</th>" for c in checks)
    rows = []
    for p in d["content"]["top_parents"]:
        cells = []
        for c in checks:
            ck = p["checks"][c]
            icon, label = STATUS_ICON[ck["status"]]
            cells.append(f'<td><span class="chip {ck["status"]}" title="{e(label)}">{icon}</span> {e(ck["detail"])}</td>')
        title = (p.get("title") or "")[:60]
        rows.append(f'<tr><th scope="row"><a href="https://www.{e(d["prospect"]["domain"])}/dp/{e(p["asin"])}">{e(p["asin"])}</a>'
                    f'<small>{e(title)}</small></th><td class="num">{p["score"]}</td>{"".join(cells)}</tr>')
    return (f'<div class="scroll"><table class="content"><thead><tr><th>Listing</th><th>Score</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def keyword_table(d: dict) -> str:
    cur = d["prospect"]["currency"]
    rows = "".join(
        f'<tr><td>{e(k["keyword"])}</td><td>{e(TIER_LABEL[k["tier"]])}</td><td class="num">{num(k["volume"])}</td>'
        f'<td class="num">{e(k["organic_rank"] or "–")}</td><td class="num">{e(k["sponsored_rank"] or "–")}</td>'
        f'<td class="num">{money(k["cpc"], cur)}</td><td><span class="kw-status {e(k["status"])}">{e(KW_STATUS[k["status"]])}</span></td></tr>'
        for k in d["strategy"]["focus_keywords"])
    return (f'<div class="scroll"><table><thead><tr><th>Keyword</th><th>Tier</th><th class="num">Searches/mo</th>'
            f'<th class="num">Organic</th><th class="num">Sponsored</th><th class="num">CPC</th><th>Status</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


def tier_table(d: dict) -> str:
    rows = "".join(f'<tr><td>{e(TIER_LABEL[t])}</td><td class="num">{v["keywords"]}</td><td class="num">{num(v["volume"])}</td>'
                   f'<td class="num">{v["gaps"]}</td></tr>' for t, v in d["strategy"]["tiers"].items())
    return (f'<table><thead><tr><th>Tier</th><th class="num">Keywords</th><th class="num">Searches/mo</th>'
            f'<th class="num">Gaps</th></tr></thead><tbody>{rows}</tbody></table>')


def attackers_html(d: dict) -> str:
    att = d["competitors"]["brand_term_attackers"]
    if not att:
        return "<p>No competitor ads seen on their brand name in the searches we ran.</p>"
    items = "".join(f'<li><b>{e(a["brand_guess"])}</b> sponsored at position {e(a["position"])} on “{e(a["keyword"])}”'
                    f'<small>{e(a["title"])}</small></li>' for a in att[:8])
    own = "They do appear in their own brand-term ads." if d["competitors"]["prospect_sponsored_on_own_brand"] \
        else "They had no sponsored placement of their own on those searches."
    return f"<ul class=\"attackers\">{items}</ul><p>{own}</p>"


def amc_html(d: dict, findings: dict) -> str:
    bench = d.get("amc_benchmark") or {}
    rows = ""
    labels = {"avg_touches_before_purchase": ("Ad touches before first purchase", lambda v: f"{v:.1f}"),
              "share_3plus_touches": ("Buyers with 3+ ad touches", pct),
              "ntb_share": ("New-to-brand share of ad sales", pct),
              "repeat_rate": ("Buyers who reorder in window", pct),
              "repeat_60d_rate": ("Reorder within 60 days", pct),
              "avg_days_to_repeat": ("Average days to reorder", lambda v: f"{v:.0f}"),
              "multi_ad_type_cvr_lift": ("Conversion lift, SP + SB/SD vs SP only", lambda v: f"{v:.1f}×")}
    for k, (label, f) in labels.items():
        m = (bench.get("metrics") or {}).get(k)
        if m:
            rows += f'<tr><td>{e(label)}</td><td class="num">{e(f(m["median"]))}</td><td class="num">{e(f(m["min"]))}–{e(f(m["max"]))}</td></tr>'
    table = (f'<table><thead><tr><th>Category benchmark ({e(bench.get("category"))})</th><th class="num">Median</th>'
             f'<th class="num">Range</th></tr></thead><tbody>{rows}</tbody></table>') if rows else ""
    hyp = "".join(f"<li>{e(h)}</li>" for h in findings.get("amc_hypotheses", []))
    qs = "".join(f"<li>{e(q)}</li>" for q in findings.get("amc_questions", []))
    rs = d["strategy"]["repeat_signals"]
    signals = (f'Repeat-purchase signals: {e(rs.get("likelihood", "unknown"))} '
               f'(Subscribe &amp; Save on {pct(rs.get("sns_share"))} of ASINs, multipacks {pct(rs.get("multipack_share"))}, '
               f'{"consumable" if rs.get("consumable_category") else "non-consumable"} category).')
    return (f'<p>{signals}</p>{table}<div class="two"><div><h3>What we expect AMC to show</h3><ul>{hyp}</ul></div>'
            f'<div><h3>Questions we would answer in week one</h3><ol>{qs}</ol></div></div>')


def method_html(d: dict) -> str:
    a = d["strategy"]["budget"]["assumptions"]
    steps = d.get("coverage", {}).get("steps", [])
    skipped = [s for s in steps if s["status"] != "ok"]
    skipped_html = "".join(f"<li>{e(s['step'])}: {e(s.get('reason') or s.get('error'))}</li>" for s in skipped)
    return (f"<p>Built from public marketplace data (Keepa, Jungle Scout, DataForSEO, Amazon catalogue and bid "
            f"recommendations) on {e(d['generated'])}. We have not seen this brand's Seller Central or advertising "
            f"account, so spend and budget figures are estimates.</p>"
            f"<p>Budget model: search volume × {a['clicks_per_search']:.0%} of searches producing an ad click × target "
            f"sponsored share of voice by tier × CPC benchmark, plus {a['retention_share']:.0%} for remarketing.</p>"
            + (f"<details><summary>Data gaps in this run</summary><ul>{skipped_html}</ul></details>" if skipped else ""))


def render(run: Path) -> tuple[Path, Path]:
    d = read_json(run / "dataset.json")
    findings = read_json(run / "findings.json")
    if not d or not findings:
        raise SystemExit(f"{run} needs dataset.json and findings.json")
    cur = d["prospect"]["currency"]
    budget = d["strategy"]["budget"]
    single = (d.get("focus") or {}).get("scope") == "asin"
    sov = d["competitors"]["share_of_voice"][:8]
    slots = {
        "TITLE": e(f'{d["prospect"]["brand"]} {d["focus"]["seed"]} {d["prospect"]["marketplace"].upper()} Audit' if single
                   else f'{d["prospect"]["brand"] or "Prospect"} Amazon Audit'),
        "EYEBROW": "Smart PPC · Single-product audit" if single else "Smart PPC · Amazon audit",
        "SUBJECT": e(((d.get("heroes") or [{}])[0].get("title") or "")[:110]) if single else "",
        "BRAND": e(d["prospect"]["brand"] or d["prospect"]["input"]),
        "MARKET": e(d["prospect"]["domain"]),
        "DATE": e(d["generated"]),
        "HEADLINE": e(findings.get("headline", "")),
        "POINTS": points_html(findings),
        "STATS": stats_html(d),
        "HEROES": heroes_html(d, findings),
        "CONTENT_TITLE": "Listing content" if single else "Content on the best-sellers",
        "SNAPSHOT_TITLE": "The product today" if single else "The business today",
        "HEROES_EYEBROW": "The listing" if single else "Best-sellers",
        "HEROES_TITLE": "Fix, push and cut" if single else "Where the money is",
        "HEROES_INTRO": ("What to fix on the listing, which searches to push and which to cut." if single
                         else "The products below make most of the revenue, so every recommendation starts here."),
        "QUICK_SECTION": "" if single else ('<section><header><span class="eyebrow">Quick wins</span>'
                                            f'<h2>Catalogue tidy-up</h2></header>{quick_wins_html(d)}</section>'),
        "CONTENT_TABLE": content_table(d),
        "CONTENT_NOTE": e(findings.get("content_note", "")),
        "AD_SUMMARY": e(findings.get("ad_strategy_summary", "")),
        "TIER_TABLE": tier_table(d),
        "KEYWORD_TABLE": keyword_table(d),
        "BUDGET_CHART": stacked(budget["monthly_by_ad_type"], cur),
        "BUDGET_TOTAL": money(budget["monthly_total"], cur),
        "ATTACKERS": attackers_html(d),
        "SOV_CHART": hbars([(r["brand"], r["avg_sov"], r["is_prospect"]) for r in sov]),
        "AMC": amc_html(d, findings),
        "METHOD": method_html(d),
    }
    page = TEMPLATE.read_text()
    for k, v in slots.items():
        page = page.replace(f"{{{{{k}}}}}", v)
    out_html = run / "audit.html"
    out_html.write_text(page)

    lines = [f"# Evidence: {d['prospect']['brand']} ({d['prospect']['domain']}, {d['generated']})", ""]
    for i, p in enumerate(findings.get("points", [])[:5], 1):
        lines += [f"## {i}. {p['title']}", "", p["detail"], ""] + [f"- {x}" for x in p.get("evidence", [])] + [""]
    lines += ["## Data coverage", "", "```json", json.dumps(d.get("coverage", {}), indent=2), "```"]
    out_md = run / "evidence.md"
    out_md.write_text("\n".join(lines))
    return out_html, out_md


if __name__ == "__main__":
    for path in render(Path(sys.argv[1])):
        print(f"✓ {path}")
````

### `analyse/pdf.py`

```python
"""Print an audit page to an A4 PDF (for attaching to the follow-up email).

    python -m analyse.pdf runs/<slug>

Uses the headless Chromium that ships with the environment. Collapsed "What we saw" sections are opened
and the light theme is forced so the PDF matches the brand colours.
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys
from pathlib import Path

from collectors.common import read_json

PRINT_CSS = ("@page{size:A4;margin:0} html,body{background:#f6f1e7;-webkit-print-color-adjust:exact;"
             "print-color-adjust:exact} .page{padding-block:14mm!important;gap:36px!important} "
             ".point,.hero-card,.stat,tr{break-inside:avoid} h2,h3{break-after:avoid}")


def chromium() -> str:
    found = os.environ.get("CHROMIUM") or next(iter(sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))), None)
    if not found:
        raise SystemExit("No Chromium found; set CHROMIUM to a Chrome/Chromium binary")
    return found


def to_pdf(run: Path) -> Path:
    d = read_json(run / "dataset.json", {})
    brand = (d.get("prospect") or {}).get("brand") or run.name
    if (d.get("focus") or {}).get("scope") == "asin":  # one product: name the file after it and the market
        brand = f'{brand}-{d["focus"]["seed"]}-{d["prospect"]["marketplace"].upper()}'
    page = (run / "audit.html").read_text()
    wrapper = run / "print.html"
    wrapper.write_text('<!doctype html><html data-theme="light"><head><meta charset="utf-8">'
                       f'<meta name="viewport" content="width=device-width,initial-scale=1"><style>{PRINT_CSS}</style>'
                       f'</head><body>{page}<script>document.querySelectorAll("details").forEach(d=>d.open=true)'
                       '</script></body></html>')
    out = run / f"{brand.replace(' ', '-')}-Amazon-Audit.pdf"
    subprocess.run([chromium(), "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    "--virtual-time-budget=5000", f"--print-to-pdf={out}", wrapper.resolve().as_uri()],
                   check=True, capture_output=True, timeout=120)
    wrapper.unlink()
    return out


if __name__ == "__main__":
    print(f"✓ {to_pdf(Path(sys.argv[1]))}")
```

### `analyse/archive.py`

```python
"""Save a finished audit into audits/<slug>/ so it's kept in the repo (runs/ is temporary and gitignored).

    python -m analyse.archive runs/<slug> [--link https://claude.ai/artifact/...]

Copies the deliverables (not the raw API dumps), writes a README for the folder and adds a row to
audits/INDEX.md. Commit and push afterwards; the script prints the commands.
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from collectors.common import ROOT, read_json

AUDITS_DIR = ROOT / "audits"
DELIVERABLES = ["email.md", "audit.html", "findings.json", "evidence.md", "dataset.json", "input.json", "job_ad.txt",
                "contacts.json"]
INDEX_HEADER = ("# Audits\n\n| Date | Brand | Marketplace | Est. revenue /mo | Audit page | Folder |\n"
                "|---|---|---|---|---|---|\n")


def email_points(email: str) -> list[str]:
    return [re.sub(r"\*\*", "", m) for m in re.findall(r"^\s*\d\.\s+(.+)$", email, re.M)]


def contact_lines(c: dict) -> list[str]:
    if not c or not c.get("website"):
        return ["- No contacts collected (pass --website)."]
    lines = [f"- **Recommended To:** {c.get('recommended_to') or '–'}"
             + (f" ({c['recommended_person']})" if c.get("recommended_person") else "")]
    for p in ((c.get("apollo") or {}).get("people") or [])[:8]:
        email = f", {p['email']} ({p.get('email_status')})" if p.get("email") else ""
        lines.append(f"- {p['name']}: {p.get('title') or '–'} at {p.get('organisation') or '–'}"
                     f"{email}{', ' + p['linkedin'] if p.get('linkedin') else ''}")
    for co in c.get("companies_house") or []:
        lines.append(f"- Companies House: {co['name']} ({co['number']}), people listed: "
                     f"{', '.join(co.get('people') or []) or '–'} {co.get('url', '')}".rstrip())
    lines += [f"- {e['email']} ({e['type']}, from {e['source']})" for e in c.get("emails", [])]
    lines += [f"- {p['name']}: {p['role']} (from {p['source']})" for p in c.get("people", [])]
    lines += [f"- Suggested: {s['email']} for {s['name']} ({s['status']})" for s in c.get("suggested", [])]
    co = c.get("company") or {}
    if co.get("name") or co.get("number"):
        lines.append(f"- Company: {co.get('name') or '–'} {('(' + co['number'] + ')') if co.get('number') else ''}".rstrip())
    if c.get("only_generic"):
        lines.append("- Only shared inboxes found; check LinkedIn:")
        lines += [f"  - [{l['org']} {l['role']}]({l['url']})" for l in (c.get("linkedin_searches") or [])[:8]]
    return lines


def archive(run: Path, link: str | None = None, audits_dir: Path = AUDITS_DIR) -> Path:
    if not (run / "dataset.json").exists():
        raise SystemExit(f"{run} has no dataset.json; run the audit first")
    dest = audits_dir / run.name
    dest.mkdir(parents=True, exist_ok=True)
    for name in DELIVERABLES:
        if (run / name).exists():
            shutil.copy2(run / name, dest / name)
    for pdf in run.glob("*-Amazon-Audit.pdf"):
        shutil.copy2(pdf, dest / pdf.name)

    d = read_json(run / "dataset.json")
    p, focus = d["prospect"], d.get("focus") or {}
    email = (run / "email.md").read_text() if (run / "email.md").exists() else ""
    gaps = [f"{s['step']}: {s.get('reason') or s.get('error')}"
            for s in (d.get("coverage") or {}).get("steps", []) if s["status"] != "ok"]
    revenue = focus.get("est_monthly_revenue")
    share = focus.get("hero_revenue_share")
    lines = [
        f"# {p['brand']} ({p['domain']})",
        "",
        f"- **Audited:** {d['generated']}",
        f"- **Input:** {p.get('input')}",
        f"- **Audit page:** {link or 'not published'}",
        f"- **Catalogue:** {focus.get('total_asins', '–')} ASINs, {focus.get('live_asins', '–')} live; "
        f"{focus.get('hero_families', '–')} best-seller families make {round(share * 100) if share else '–'}% "
        f"of ~{p['currency']}{revenue:,.0f}/mo" if revenue else "- **Catalogue:** –",
        "",
        "## Email points",
        "",
        *[f"{i}. {pt}" for i, pt in enumerate(email_points(email), 1)],
        "",
        "## Contacts",
        "",
        *contact_lines(read_json(run / "contacts.json", {})),
        "",
        "## Data gaps",
        "",
        *([f"- {g}" for g in gaps] or ["- none"]),
        "",
        "Files: `email.md` (outreach script), `audit.html` (detailed report), `evidence.md` (sources), "
        "`findings.json`, `dataset.json`.",
        "",
    ]
    (dest / "README.md").write_text("\n".join(lines))

    index = audits_dir / "INDEX.md"
    text = index.read_text() if index.exists() else INDEX_HEADER
    row = (f"| {d['generated']} | {p['brand']} | {p['domain']} | "
           f"{p['currency']}{revenue:,.0f} | {link or '–'} | [{run.name}]({run.name}/) |" if revenue else
           f"| {d['generated']} | {p['brand']} | {p['domain']} | – | {link or '–'} | [{run.name}]({run.name}/) |")
    rows = [r for r in text.splitlines() if f"[{run.name}]" not in r]  # re-archiving replaces the row
    index.write_text("\n".join(rows).rstrip("\n") + "\n" + row + "\n")
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path)
    ap.add_argument("--link", help="published audit page URL")
    args = ap.parse_args()
    dest = archive(args.run, args.link)
    brand = read_json(args.run / "dataset.json")["prospect"]
    print(f"✓ saved {dest.relative_to(ROOT)}")
    print(f'  git add audits && git commit -m "Audit: {brand["brand"]} ({brand["marketplace"]})" && git push')


if __name__ == "__main__":
    main()
```

## 6.5 AMC benchmark queries and config

### `amc_queries/ad_type_overlap.sql`

```sql
-- Purchase rate by combination of sponsored ad types a shopper was exposed to.
-- Output columns: sp, sb, sd, exposed_users, purchasers
WITH exposure AS (
  SELECT user_id,
         MAX(CASE WHEN ad_product_type = 'sponsored_products' THEN 1 ELSE 0 END) AS sp,
         MAX(CASE WHEN ad_product_type = 'sponsored_brands' THEN 1 ELSE 0 END) AS sb,
         MAX(CASE WHEN ad_product_type = 'sponsored_display' THEN 1 ELSE 0 END) AS sd
  FROM sponsored_ads_traffic
  WHERE user_id IS NOT NULL
  GROUP BY user_id
),
buyers AS (
  SELECT user_id, 1 AS purchased
  FROM conversions
  WHERE event_subtype = 'order' AND user_id IS NOT NULL
  GROUP BY user_id
)
SELECT e.sp, e.sb, e.sd,
       COUNT(e.user_id) AS exposed_users,
       SUM(COALESCE(b.purchased, 0)) AS purchasers
FROM exposure e
LEFT JOIN buyers b ON b.user_id = e.user_id
GROUP BY e.sp, e.sb, e.sd
```

### `amc_queries/new_to_brand.sql`

```sql
-- Share of ad-attributed purchases that were new-to-brand (no brand purchase in prior 12 months).
-- Output columns: purchases, ntb_purchases
SELECT
  SUM(purchases) AS purchases,
  SUM(new_to_brand_purchases) AS ntb_purchases
FROM amazon_attributed_events_by_conversion_time
```

### `amc_queries/path_to_purchase.sql`

```sql
-- Ad touches before each converting user's FIRST purchase, bucketed.
-- Output columns: touch_bucket, users
-- Validate column names in the AMC schema explorer for your instance before first use.
WITH touches AS (
  SELECT user_id, event_dt FROM sponsored_ads_traffic WHERE user_id IS NOT NULL
  UNION ALL
  SELECT user_id, impression_dt AS event_dt FROM dsp_impressions WHERE user_id IS NOT NULL
),
first_purchase AS (
  SELECT user_id, MIN(event_dt) AS first_purchase_dt
  FROM conversions
  WHERE event_subtype = 'order' AND user_id IS NOT NULL
  GROUP BY user_id
),
per_user AS (
  SELECT p.user_id, COUNT(t.event_dt) AS touches
  FROM first_purchase p
  LEFT JOIN touches t ON t.user_id = p.user_id AND t.event_dt <= p.first_purchase_dt
  GROUP BY p.user_id
)
SELECT
  CASE WHEN touches >= 5 THEN '5+' ELSE CAST(touches AS VARCHAR) END AS touch_bucket,
  COUNT(user_id) AS users
FROM per_user
GROUP BY 1
```

### `amc_queries/repeat_rate.sql`

```sql
-- Repeat-purchase behaviour: share of buyers who order again, and how fast.
-- Use a long time window (>= 6 months) so repurchase cycles fit inside it.
-- Output columns: buyers, repeat_buyers, repeat_30d, repeat_60d, repeat_90d, avg_days_to_repeat
WITH orders AS (
  SELECT user_id, event_dt
  FROM conversions
  WHERE event_subtype = 'order' AND user_id IS NOT NULL
),
ranked AS (
  SELECT user_id, event_dt, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY event_dt) AS n
  FROM orders
),
firsts AS (
  SELECT user_id,
         MAX(CASE WHEN n = 1 THEN event_dt END) AS d1,
         MAX(CASE WHEN n = 2 THEN event_dt END) AS d2
  FROM ranked
  GROUP BY user_id
)
SELECT
  COUNT(user_id) AS buyers,
  SUM(CASE WHEN d2 IS NOT NULL THEN 1 ELSE 0 END) AS repeat_buyers,
  SUM(CASE WHEN d2 IS NOT NULL AND DATE_DIFF('day', d1, d2) <= 30 THEN 1 ELSE 0 END) AS repeat_30d,
  SUM(CASE WHEN d2 IS NOT NULL AND DATE_DIFF('day', d1, d2) <= 60 THEN 1 ELSE 0 END) AS repeat_60d,
  SUM(CASE WHEN d2 IS NOT NULL AND DATE_DIFF('day', d1, d2) <= 90 THEN 1 ELSE 0 END) AS repeat_90d,
  AVG(CASE WHEN d2 IS NOT NULL THEN DATE_DIFF('day', d1, d2) END) AS avg_days_to_repeat
FROM firsts
```

### `amc_instances.example.json`

```json
[
  {
    "label": "client-a-us",
    "category": "Pet Supplies",
    "marketplace": "us",
    "instance_id": "amcxxxxxxxx",
    "advertiser_id": "ENTITYxxxxxxxx"
  }
]
```

## 6.6 Setup and docs

### `.env.example`

```bash
# Copy to .env (never commit). Any provider left blank is skipped; the audit gets thinner.

# Keepa (required: ASIN map, listing content, history)
KEEPA_KEY=

# Cloud sessions: providers whose key is stored as a network secret (the proxy adds it, so leave
# their keys below blank). Jungle Scout and DataForSEO support this; Keepa (key in URL) and the
# Amazon APIs (OAuth exchange) need the plain variables.
APA_PROXY_AUTH=

# Jungle Scout API (sales estimates, keywords by ASIN, share of voice)
JS_KEY_NAME=
JS_KEY=

# DataForSEO (live Amazon SERPs; ranked keywords fallback)
DATAFORSEO_LOGIN=
DATAFORSEO_PASSWORD=

# SP-API (Catalog Items: brand search + authoritative images/bullets). LWA app from your own seller account.
SPAPI_CLIENT_ID=
SPAPI_CLIENT_SECRET=
SPAPI_REFRESH_TOKEN=

# Amazon Ads API (bid recommendations as CPC benchmark; AMC benchmarks)
ADS_CLIENT_ID=
ADS_CLIENT_SECRET=
ADS_REFRESH_TOKEN=
ADS_PROFILE_ID_US=
ADS_PROFILE_ID_UK=
# An ASIN you advertise in each marketplace, used as the proxy for bid recommendations
ADS_BENCH_ASIN_US=
ADS_BENCH_ASIN_UK=

# Apollo.io (people at the brand / parent company / Amazon seller, with LinkedIn and verified emails).
# Cloud: either set APOLLO_API_KEY plus api.apollo.io in Allowed domains, or store the key as a network
# secret (custom header x-api-key, no prefix, host api.apollo.io) and add apollo to APA_PROXY_AUTH.
APOLLO_API_KEY=

# Per-run caps (Keepa tokens; request counts for the rest)
APA_BUDGET_KEEPA=400
APA_BUDGET_JS=60
APA_BUDGET_D4S=40
APA_BUDGET_SPAPI=60
APA_BUDGET_ADS=20
APA_BUDGET_APOLLO_SEARCH=10
APA_BUDGET_APOLLO_CREDITS=3
```

### `README.md`

````markdown
# Amazon Prospect Audit

An outside-in audit of a prospect's Amazon business, used for consultant outreach. Paste in a brand store URL, a
product URL, an ASIN or a brand name, and optionally a job advert. You get back:

- **`email.md`**: a short outreach email with up to 5 points, written in the prospect's own words
- **`audit.html`**: a one-page visual audit covering the catalogue, listing content, keyword map and budget,
  competitors, and AMC hypotheses
- **`evidence.md`**: the data behind every claim

The Python collectors pull and compute the numbers. The Claude skill in `.claude/skills/outreach/` decides what
matters and writes the output.

## Two skills
- **`outreach`** (`.claude/skills/outreach/`): the outside-in prospect audit above, in Smart PPC style, with the
  outreach email. Start a chat with "use the outreach skill to audit <brand store URL / ASIN>".
- **`internal-audit`** (`.claude/skills/internal-audit/`): a client-branded review built from the client's own
  Seller Central and Amazon Ads exports (Business Reports, Search Query Performance, Sponsored Products advertised
  product / search term / targeting / placement reports, campaign list). The skill lists which reports to pull;
  `analyse/internal_audit.py` builds the numbers and `analyse/internal_report.py` renders the PDF. Needs `pandas`
  and `openpyxl` (preinstalled in the cloud environment).

## Setup
```bash
cp .env.example .env   # fill in what you have; Keepa is the only hard requirement
python -m pytest       # offline tests, no keys needed
```
Python 3.11+ is required. There are no third-party dependencies at runtime; `pytest` is only needed for the tests.

### Cloud sessions
Store keys on the cloud environment rather than in the repo:
| Provider | How | Host |
|---|---|---|
| Keepa | environment variable `KEEPA_KEY` (key travels in the URL), plus `api.keepa.com` in Allowed domains | `api.keepa.com` |
| Jungle Scout | network secret, custom header `Authorization`, no prefix, value `KEYNAME:KEY` | `developer.junglescout.com` |
| DataForSEO | network secret, Username and password | `api.dataforseo.com` |
| SP-API / Ads API | environment variables (`SPAPI_*`, `ADS_*`), plus their hosts in Allowed domains | see `collectors/common.py` |

For providers on network secrets, set `APA_PROXY_AUTH=junglescout,dataforseo` as an environment variable so the
collectors call them without a local key.

## Use
In Claude Code, from this repo:
> audit https://www.amazon.co.uk/stores/Acme/page/… (here's their job ad: …)

Or run the steps yourself:
```bash
python run_audit.py "<url | ASIN | brand>" --job-ad job.txt   # → runs/<slug>/dataset.json
# write runs/<slug>/findings.json (the skill does this)
python -m analyse.render runs/<slug>                          # → audit.html, evidence.md
```

## Finding contacts
Each audit researches the companies behind the brand: the brand, the company that runs its website, and
its Amazon seller. It then looks for the most direct contact:
- emails published on the brand's site, or found by web search
- Companies House people for active UK companies with an exact name match
- one-click LinkedIn searches for each company
- with an Apollo.io key: people currently in founder, ecommerce, Amazon and marketing roles, with
  LinkedIn profiles and verified work emails for the top 3 (each verified email uses 1 Apollo credit)

Contacts are saved with the audit and never appear on the shareable audit page.

## Where audits are saved
Each run works in `runs/<brand>-<marketplace>-<date>/`, which is temporary and not committed. When an
audit is finished, the skill saves it to `audits/<brand>-<marketplace>-<date>/` and adds it to
`audits/INDEX.md`, the running list of every prospect audited. Each saved folder holds:
- `email.md`: the outreach script
- `audit.html`: the detailed report (open it in a browser, or use its published link)
- `evidence.md`: the data behind each claim
- a `README.md` summary

## What it can and can't see
| Area | Source | Notes |
|---|---|---|
| ASIN map, content, growth | Keepa, SP-API Catalog | Images, video, A+, bullets, variations, listing dates, BSR and review history |
| Sales | Jungle Scout | Estimates for the top parents |
| Keywords, ranks, CPC | Jungle Scout (DataForSEO fallback), Ads API bid recs | Bid recommendations use your own proxy ASIN |
| Who's advertising | DataForSEO live SERPs, Jungle Scout share of voice | Sponsored placements we can observe |
| Ad spend | Estimated | Nobody can see a prospect's real spend or bids |
| AMC | Benchmarks from your managed instances | Category medians only, never the prospect's own data |

## AMC benchmarks (monthly)
```bash
cp amc_instances.example.json amc_instances.json   # list instances you manage + their category
python -m collectors.amc_bench --start 2026-04-01 --end 2026-09-30
```
This writes `benchmarks/amc_<category>.json` (gitignored). A category needs 3 or more instances before its benchmark
is treated as solid. Validate the SQL in `amc_queries/` in the AMC query editor before the first run.

## Costs
Each run is capped by the `APA_BUDGET_*` variables. API responses are cached in `runs/.cache` for 7 days, so
re-rendering or re-running the same prospect is free. `collect_log.json` records what each run used.
````

## 6.7 Tests and offline sample data

### `tests/__init__.py`

(empty file: marks the folder as a Python package)

```python

```

### `tests/sample_run.py`

```python
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
```

### `tests/test_pipeline.py`

The last three tests ("internal audit") cover the separate internal-audit skill; they are kept so the file is verbatim.

```python
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


def test_short_brand_names_match_whole_words_only():
    from collectors.junglescout import brand_matches
    assert brand_matches({"brand": "W7", "title": "W7 Beauty Blast"}, "W7")
    assert brand_matches({"brand": None, "title": "W7 Beauty Blast Advent Calendar"}, "W7")
    assert not brand_matches({"brand": "NICETOWN", "title": "Blackout Curtains W70 x L84"}, "W7")
    assert not brand_matches({"brand": "HEYDUDE", "title": "HEYDUDE Women's Wendy Slip Size W7"}, "W7")
    assert brand_matches({"brand": "Super Facialist", "title": "x"}, "SuperFacialist")


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


def test_off_target_qualifiers_and_brand_seller():
    from analyse import checks
    title = "W7 Beauty Blast Makeup Advent Calendar 2026 - 24 Cosmetic Treats"
    kws = [{"keyword": "squishy advent calendar 2026", "sponsored_rank": 4, "organic_rank": 55, "volume": 176333},
           {"keyword": "lego advent calendar", "sponsored_rank": 8, "organic_rank": 74, "volume": 30767},
           {"keyword": "beauty advent calendar 2026", "sponsored_rank": 3, "organic_rank": 1, "volume": 26967},
           {"keyword": "make up set", "sponsored_rank": 11, "organic_rank": None, "volume": 17533},
           {"keyword": "advent calendar 2026 for women", "sponsored_rank": 2, "organic_rank": 120, "volume": 58537}]
    out = {w["keyword"]: w["reason"] for w in checks.wasted_terms(title, "W7", kws)}
    assert out == {"squishy advent calendar 2026": 'different product ("squishy")',
                   "lego advent calendar": 'different product ("lego")'}
    assert checks.brand_seller(["Warpaint Cosmetics"] * 72 + ["Sabrikas"] * 16 + ["Amazon"] * 30) == "Warpaint Cosmetics"
    assert checks.brand_seller(["A"] * 10 + ["B"] * 8) is None


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

def test_new_listings_are_not_judged_on_stock():
    import datetime as dt
    from analyse import checks
    recent = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    assert checks.stock_flag({"oos_pct_90": 34, "listed_since": recent}) is None
    assert checks.stock_flag({"oos_pct_90": 34, "listed_since": "2020-01-01"})


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


# --- internal audit ------------------------------------------------------------------------------

def _ia_cfg():
    return {"brand_terms": ["w7", "beauty blast"], "rivals": ["sephora", "elf"], "category_words": ["beauty", "makeup"],
            "off_target": ["needoh", "squishy"]}


def test_internal_audit_detects_reports_by_columns():
    import pandas as pd
    from analyse.internal_audit import detect
    assert detect(pd.DataFrame(columns=["Search Query", "Purchases: ASIN Count"])) == "sqp"
    assert detect(pd.DataFrame(columns=["(Child) ASIN", "Sessions - Total"])) == "business"
    assert detect(pd.DataFrame(columns=["Customer Search Term", "Spend"])) == "search_term"
    assert detect(pd.DataFrame(columns=["Placement", "Bidding strategy"])) == "placement"
    assert detect(pd.DataFrame(columns=["Targeting", "Top-of-search Impression Share"])) == "targeting"
    assert detect(pd.DataFrame(columns=["Advertised ASIN", "Date"])) == "advertised"
    assert detect(pd.DataFrame(columns=["Campaign name", "Top-of-search bid adjustment"])) == "campaigns"
    assert detect(pd.DataFrame(columns=["Foo"])) is None


def test_internal_audit_groups_searches():
    from analyse.internal_audit import bucket, classify_query
    cfg = _ia_cfg()
    assert classify_query("beauty advent calendar 2026", 1.2, cfg) == "push"
    assert classify_query("beauty advent calendar", 0.95, cfg) == "hold"
    assert classify_query("advent calendar 2026", 0.3, cfg) == "cut"
    assert classify_query("w7 advent calendar", 2.0, cfg) == "defend"
    assert classify_query("sephora advent calendar", 0.5, cfg) == "test"
    assert classify_query("needoh advent calendar", 3.0, cfg) == "cut"
    assert classify_query("amazon beauty advent calendar", 1.2, cfg) == "cut"
    assert classify_query("selfie calendar", 0.5, cfg) == "cut"  # "elf" only matches as a whole word
    assert bucket("b0abcdef12", cfg) == "Rival product pages"
    assert bucket("makeup advent calendar", cfg) == "Category searches"
    assert bucket("advent calendar for teen girls", cfg) == "Audience searches"
    assert bucket("advent calendar 2026", cfg) == "Generic searches"


def test_internal_audit_sqp_and_placement():
    import pandas as pd
    from analyse.internal_audit import placement, sqp
    week = pd.DataFrame([
        {"Search Query": "makeup advent calendar", "Search Query Volume": 1000, "Impressions: Total Count": 1000,
         "Impressions: ASIN Count": 40, "Clicks: Total Count": 100, "Clicks: ASIN Count": 10,
         "Purchases: Total Count": 20, "Purchases: ASIN Count": 4},
        {"Search Query": "advent calendar", "Search Query Volume": 50000, "Impressions: Total Count": 9000,
         "Impressions: ASIN Count": 9, "Clicks: Total Count": 1000, "Clicks: ASIN Count": 20,
         "Purchases: Total Count": 500, "Purchases: ASIN Count": 3}])
    out = sqp([("2026-10-17", "2026-10-11", week)], 3, _ia_cfg())
    rows = {r["query"]: r for r in out["rows"]}
    assert rows["makeup advent calendar"]["group"] == "push" and rows["makeup advent calendar"]["ratio"] == 2.0
    assert rows["advent calendar"]["group"] == "cut"
    p = pd.DataFrame([
        {"Campaign Name": "A", "Placement": "Top of Search on Amazon", "Spend": "100", "Clicks": 10, "Impressions": 1,
         "7 Day Total Sales": 50, "7 Day Total Orders (#)": 2},
        {"Campaign Name": "A", "Placement": "Rest of search on Amazon", "Spend": 50, "Clicks": 10, "Impressions": 1,
         "7 Day Total Sales": 100, "7 Day Total Orders (#)": 4},
        {"Campaign Name": "B", "Placement": "Top of Search on Amazon", "Spend": 999, "Clicks": 1, "Impressions": 1,
         "7 Day Total Sales": 0, "7 Day Total Orders (#)": 0}])
    pl = placement(p, ["A"])
    tos = next(r for r in pl["by_placement"] if r["Placement"].startswith("Top"))
    assert tos["spend"] == 100 and round(tos["share"]) == 67 and tos["cost_per_order"] == 50
```

---

## 7. Worked example: `audits/ultradex-uk-2026-10-21/` (verbatim)

Created by `run_audit.py` for the UltraDEX brand store on amazon.co.uk on 21 October 2026, then `analyse.render`, `analyse.pdf` and `analyse.archive`. Files below are copied as they are, except that the Companies House officer names in `contacts.json` are replaced with a count (they are public-register personal data and add nothing to the handover).

### `audits/ultradex-uk-2026-10-21/README.md`

```markdown
# UltraDEX (amazon.co.uk)

- **Audited:** 2026-10-21
- **Input:** https://www.amazon.co.uk/stores/UltraDEX/page/02885511-9448-4D57-A25F-B3812F09FE2C?lp_asin=B071Z1B158
- **Audit page:** https://claude.ai/artifact/TKhhwmpufa9XDryV2gj4rV
- **Catalogue:** 84 ASINs, 45 live; 6 best-seller families make 85% of ~£99,890/mo

## Email points

1. You're barely advertising on your biggest searches. Only 1 of your top 30 keywords has an UltraDEX ad. Your Fresh Breath Spray ranks #6 for "bad breath" (73,600 searches a month) with nothing behind it.
2. CB12 is advertising on your brand name. It takes an ad slot when people search "ultradex", and you have no ads there yourself.
3. Your 12hr Low-Abrasion Toothpaste listing isn't finished. It has 5 images, no video and no A+, while your rinses have all three.
4. Your pack sizes are listed separately. The 12-pack spray and 6-pack rinses have their own listings, which splits your reviews and sales rank.

## Contacts

- **Recommended To:** –
- Companies House: PERIPRODUCTS LIMITED (02864374), people listed: BERNHOLT, Richard Paul, COLLINS, Sharon Mary, COUZENS, Angela Christina, GIOFFRE, Giuseppe, GLASSMAN, David Michael, HIGHAM, Quentin Giles Anthony, HITCHEN, Louisa, HUNTER, James Douglas, KRIEGER, Simon, MCCARTHY, Louise, NCUBE, David Bafana, POTTS, Michael Thomas, RANDALL, Jeremy Anthony Phillip, SHEPHERD, Peter, STALBOW, Michael Robert, WATERS, Mark Andrew, WELLS, Daniel James https://find-and-update.company-information.service.gov.uk/company/02864374/officers
- Company: Periproducts Limited

## Data gaps

- images: can't reach m.media-amazon.com (<urlopen error Tunnel connection failed: 403 Forbidden>); add it to Allowed domains
- spapi.items: SP-API not configured
- ads.bids: Ads API not configured; using Jungle Scout PPC bids

Files: `email.md` (outreach script), `audit.html` (detailed report), `evidence.md` (sources), `findings.json`, `dataset.json`.
```

### `audits/ultradex-uk-2026-10-21/input.json`

```json
{
  "input": "https://www.amazon.co.uk/stores/UltraDEX/page/02885511-9448-4D57-A25F-B3812F09FE2C?lp_asin=B071Z1B158",
  "brand": "UltraDEX",
  "seller_id": null,
  "store_page_id": "02885511-9448-4D57-A25F-B3812F09FE2C",
  "seed_asins": [
    "B071Z1B158"
  ],
  "marketplace": "uk",
  "brand_slug": "UltraDEX"
}
```

### `audits/ultradex-uk-2026-10-21/email.md`

```markdown
**Subject:** CB12 is buying ads on "ultradex" searches

Hi <first name>,

I took a quick look at UltraDEX on Amazon UK. Your best-sellers have strong listings and thousands of great reviews, but four things stood out:

1. **You're barely advertising on your biggest searches.** Only 1 of your top 30 keywords has an UltraDEX ad. Your Fresh Breath Spray ranks #6 for "bad breath" (73,600 searches a month) with nothing behind it.
2. **CB12 is advertising on your brand name.** It takes an ad slot when people search "ultradex", and you have no ads there yourself.
3. **Your 12hr Low-Abrasion Toothpaste listing isn't finished.** It has 5 images, no video and no A+, while your rinses have all three.
4. **Your pack sizes are listed separately.** The 12-pack spray and 6-pack rinses have their own listings, which splits your reviews and sales rank.

A bit about me: I run Smart PPC, a UK-based Amazon consultancy that combines hands-on account management with AI-powered tools to grow brands on Amazon. I currently have 1 slot available to work with a brand on a freelance basis, fully managing their Amazon account (stock, content, ads and new product development strategy) for £950 a month, with no fixed contracts.

I've put together a more detailed report, product by product, with exactly what I'd change. Happy to send it across free of charge if it's useful.

If this isn't relevant, just let me know and I won't follow up.

<Signature>
```

### `audits/ultradex-uk-2026-10-21/findings.json`

```json
{
  "headline": "UltraDEX's listings are strong and well reviewed, but it advertises on almost none of its biggest searches, and a competitor is buying the ad slot on its own brand name.",
  "points": [
    {
      "category": "advertising",
      "title": "Put ad support behind the big searches where UltraDEX already ranks",
      "detail": "Only 1 of the top 30 keywords across the best-sellers has an UltraDEX ad. The Fresh Breath Spray ranks #6 organically for 'bad breath' (73.6k/mo) with no ad, and the rinses sit at #39 for 'mouth wash' (24.7k/mo) and #49 for 'bad breath'. Exact-match ads on these terms are the fastest visibility win.",
      "evidence": [
        "Sponsored coverage: 1 of top 30 keywords (Jungle Scout keywords by ASIN)",
        "bad breath: 73,603/mo; Spray organic #6, Fluoride Rinse organic #49, no sponsored rank",
        "mouth wash: 24,719/mo; Fluoride Rinse organic #39, no sponsored rank",
        "toothpaste: 392,821/mo; Low-Abrasion Toothpaste organic #47, no sponsored rank, CPC ~£0.49"
      ],
      "job_ad_quote": null
    },
    {
      "category": "advertising",
      "title": "Defend the UltraDEX brand searches from CB12",
      "detail": "CB12 Mouthwash takes a sponsored slot at #4 on 'ultradex' and #15 on 'ultradex mouthwash', and UltraDEX runs no ads on its own name. Brand-term ads are cheap and keep loyal buyers from switching.",
      "evidence": [
        "'ultradex': CB12 Mouthwash sponsored at position 4 (DataForSEO, Amazon UK)",
        "'ultradex mouthwash': CB12 sponsored at position 15",
        "No UltraDEX sponsored placement on either brand search"
      ],
      "job_ad_quote": null
    },
    {
      "category": "catalogue",
      "title": "Bring the multipacks into their product families",
      "detail": "Pack sizes are listed separately from their main products, e.g. the Fresh Breath Spray 12-pack, '6 x Daily Oral Rinse 250ml' and the toothpaste 6-packs. That splits reviews and sales rank across six sets of duplicate listings. Merging them into variation families pools both.",
      "evidence": [
        "6 duplicate groups among live listings (title match, different parents)",
        "e.g. B0BG676CYD (Spray 12-pack) separate from B00HIXUCNC (single)",
        "e.g. B016KXU6OK '6 x UltraDex Daily Oral Rinse 250ml' separate from the rinse family"
      ],
      "job_ad_quote": null
    },
    {
      "category": "content",
      "title": "12hr Low-Abrasion Toothpaste: finish the listing",
      "detail": "This newer best-seller family (~£7–8k/mo, 57 reviews) has 5 images, no video and no A+, and its title cuts off on mobile before the pack size. Bringing it up to the standard of the rinses would help it convert.",
      "evidence": [
        "B0BG66FF4T: 5 images, 0 videos, no A+ (Keepa)",
        "Title cut off before the size in mobile search (first 80 characters)",
        "57 reviews, 4.6★"
      ],
      "job_ad_quote": null
    }
  ],
  "hero_actions": {
    "B071VT9KBZ": "Add ads on 'alcohol free mouthwash' (3.1k/mo, organic #43).",
    "B007Y5XCZE": "Exact-match ads on 'mouth wash' and 'bad breath'; drop 'otrivine' (sponsored #1, unrelated).",
    "B007Y5XD3A": "Test ads on 'toothpaste' and 'whitening toothpaste', where it ranks #47–48 with no ad support.",
    "B00HIXUCNC": "Back the #6 organic rank on 'bad breath' with ads, and add a 7th gallery image.",
    "B071Z1B158": "Fold the 250ml 6-pack and 1L into the rinse families; add ads on 'fluoride mouth rinse'.",
    "B0BG66FF4T": "Add video and A+, a 6th and 7th image, and move the pack size into the first 80 characters of the title."
  },
  "mobile_review": {},
  "content_note": "The rinses and the spray are well built for mobile (2000px zoomable images, brand videos, phone-friendly A+). The newer 12hr toothpaste is the gap.",
  "ad_strategy_summary": "UltraDEX is almost absent from paid search on its biggest terms. Defend the brand name first, then add exact-match ads where products already rank on page 1–3 ('bad breath', 'mouth wash', 'toothpaste').",
  "amc_hypotheses": [
    "Most best-sellers offer Subscribe & Save in a repeat-purchase category, so repeat buyers are likely a large share of rinse and spray revenue.",
    "With CB12 advertising on the brand name, some existing UltraDEX buyers are probably being tempted to switch at the point of reordering."
  ],
  "amc_questions": [
    "How many rinse buyers reorder, and after how many days?",
    "Do spray buyers go on to buy the rinse or toothpaste?",
    "How many shoppers who search 'ultradex' end up buying CB12?"
  ]
}
```

### `audits/ultradex-uk-2026-10-21/evidence.md`

````markdown
# Evidence: UltraDEX (amazon.co.uk, 2026-10-21)

## 1. Put ad support behind the big searches where UltraDEX already ranks

Only 1 of the top 30 keywords across the best-sellers has an UltraDEX ad. The Fresh Breath Spray ranks #6 organically for 'bad breath' (73.6k/mo) with no ad, and the rinses sit at #39 for 'mouth wash' (24.7k/mo) and #49 for 'bad breath'. Exact-match ads on these terms are the fastest visibility win.

- Sponsored coverage: 1 of top 30 keywords (Jungle Scout keywords by ASIN)
- bad breath: 73,603/mo; Spray organic #6, Fluoride Rinse organic #49, no sponsored rank
- mouth wash: 24,719/mo; Fluoride Rinse organic #39, no sponsored rank
- toothpaste: 392,821/mo; Low-Abrasion Toothpaste organic #47, no sponsored rank, CPC ~£0.49

## 2. Defend the UltraDEX brand searches from CB12

CB12 Mouthwash takes a sponsored slot at #4 on 'ultradex' and #15 on 'ultradex mouthwash', and UltraDEX runs no ads on its own name. Brand-term ads are cheap and keep loyal buyers from switching.

- 'ultradex': CB12 Mouthwash sponsored at position 4 (DataForSEO, Amazon UK)
- 'ultradex mouthwash': CB12 sponsored at position 15
- No UltraDEX sponsored placement on either brand search

## 3. Bring the multipacks into their product families

Pack sizes are listed separately from their main products, e.g. the Fresh Breath Spray 12-pack, '6 x Daily Oral Rinse 250ml' and the toothpaste 6-packs. That splits reviews and sales rank across six sets of duplicate listings. Merging them into variation families pools both.

- 6 duplicate groups among live listings (title match, different parents)
- e.g. B0BG676CYD (Spray 12-pack) separate from B00HIXUCNC (single)
- e.g. B016KXU6OK '6 x UltraDex Daily Oral Rinse 250ml' separate from the rinse family

## 4. 12hr Low-Abrasion Toothpaste: finish the listing

This newer best-seller family (~£7–8k/mo, 57 reviews) has 5 images, no video and no A+, and its title cuts off on mobile before the pack size. Bringing it up to the standard of the rinses would help it convert.

- B0BG66FF4T: 5 images, 0 videos, no A+ (Keepa)
- Title cut off before the size in mobile search (first 80 characters)
- 57 reviews, 4.6★

## Data coverage

```json
{
  "steps": [
    {
      "step": "keepa.token",
      "status": "ok",
      "tokens_left": 2,
      "per_minute": 1
    },
    {
      "step": "js.catalog.spellings",
      "status": "ok",
      "searched": [
        "UltraDEX",
        "Ultra DEX"
      ]
    },
    {
      "step": "js.catalog",
      "status": "ok",
      "asins": 84
    },
    {
      "step": "focus",
      "status": "ok",
      "live": 45,
      "hero_families": 6,
      "revenue_share": 0.85
    },
    {
      "step": "keepa.heroes",
      "status": "ok",
      "fetched": 13,
      "waited_min": 8.5
    },
    {
      "step": "images",
      "status": "skipped",
      "reason": "can't reach m.media-amazon.com (<urlopen error Tunnel connection failed: 403 Forbidden>); add it to Allowed domains"
    },
    {
      "step": "spapi.items",
      "status": "skipped",
      "reason": "SP-API not configured"
    },
    {
      "step": "keywords",
      "status": "ok",
      "heroes": 6,
      "keywords": 308
    },
    {
      "step": "js.sov",
      "status": "ok",
      "keywords": 13
    },
    {
      "step": "d4s.serp",
      "status": "ok",
      "keywords": 10
    },
    {
      "step": "ads.bids",
      "status": "skipped",
      "reason": "Ads API not configured; using Jungle Scout PPC bids"
    },
    {
      "step": "contacts",
      "status": "ok",
      "website": "https://ultradex.co.uk",
      "emails": 0
    }
  ],
  "budget": {
    "keepa": {
      "used": 10,
      "limit": 400.0
    },
    "junglescout": {
      "used": 21,
      "limit": 60.0
    },
    "dataforseo": {
      "used": 12.099999999999996,
      "limit": 40.0
    },
    "spapi": {
      "used": 0,
      "limit": 60.0
    },
    "ads": {
      "used": 0,
      "limit": 20.0
    },
    "apollo_search": {
      "used": 0,
      "limit": 10.0
    },
    "apollo_credits": {
      "used": 0,
      "limit": 3.0
    }
  },
  "collected_at": "2026-10-21T07:41:36.212585+00:00"
}
```
````

### `audits/ultradex-uk-2026-10-21/contacts.json`

Officer names replaced with a count; everything else as saved.

```json
{
  "website": "https://ultradex.co.uk",
  "domain": "ultradex.co.uk",
  "pages_checked": [
    "https://ultradex.co.uk/",
    "https://ultradex.co.uk/pages/contact",
    "https://ultradex.co.uk/contact",
    "https://ultradex.co.uk/contact-us",
    "https://ultradex.co.uk/pages/contact-us",
    "https://ultradex.co.uk/pages/about",
    "https://ultradex.co.uk/pages/about-us",
    "https://ultradex.co.uk/about"
  ],
  "emails": [],
  "people": [],
  "company": {
    "name": "Periproducts Limited",
    "number": null
  },
  "email_format": null,
  "suggested": [],
  "recommended_to": null,
  "only_generic": false,
  "organisations": [
    {
      "name": "UltraDEX",
      "kind": "brand"
    },
    {
      "name": "Periproducts Limited",
      "kind": "website operator"
    }
  ],
  "companies_house": [
    {
      "number": "02864374",
      "name": "PERIPRODUCTS LIMITED",
      "address": "Festival House, Jessop Avenue, Cheltenham, England, GL50 3SH",
      "active": true,
      "status": "Incorporated on 20 October 1993",
      "people": [
        "[17 officer names from Companies House, removed for this handover]"
      ],
      "url": "https://find-and-update.company-information.service.gov.uk/company/02864374/officers"
    }
  ],
  "linkedin_profiles": [],
  "linkedin_searches": [
    {
      "org": "UltraDEX",
      "role": "founder",
      "url": "https://www.linkedin.com/search/results/people/?keywords=%22UltraDEX%22%20founder"
    },
    {
      "org": "UltraDEX",
      "role": "ecommerce",
      "url": "https://www.linkedin.com/search/results/people/?keywords=%22UltraDEX%22%20ecommerce"
    },
    {
      "org": "UltraDEX",
      "role": "amazon",
      "url": "https://www.linkedin.com/search/results/people/?keywords=%22UltraDEX%22%20amazon"
    },
    {
      "org": "UltraDEX",
      "role": "marketing",
      "url": "https://www.linkedin.com/search/results/people/?keywords=%22UltraDEX%22%20marketing"
    },
    {
      "org": "Periproducts Limited",
      "role": "founder",
      "url": "https://www.linkedin.com/search/results/people/?keywords=%22Periproducts%20Limited%22%20founder"
    },
    {
      "org": "Periproducts Limited",
      "role": "ecommerce",
      "url": "https://www.linkedin.com/search/results/people/?keywords=%22Periproducts%20Limited%22%20ecommerce"
    },
    {
      "org": "Periproducts Limited",
      "role": "amazon",
      "url": "https://www.linkedin.com/search/results/people/?keywords=%22Periproducts%20Limited%22%20amazon"
    },
    {
      "org": "Periproducts Limited",
      "role": "marketing",
      "url": "https://www.linkedin.com/search/results/people/?keywords=%22Periproducts%20Limited%22%20marketing"
    }
  ],
  "apollo_people_url": "https://app.apollo.io/#/people?organizationIds[]=54a1296c69702d8b19581702",
  "note": "No emails published on ultradex.co.uk. Companies House lists current and past officers; check roles before use."
}
```

### `audits/ultradex-uk-2026-10-21/dataset.json`

The full dataset the audit was written from.

```json
{
  "prospect": {
    "brand": "UltraDEX",
    "marketplace": "uk",
    "domain": "amazon.co.uk",
    "currency": "\u00a3",
    "input": "https://www.amazon.co.uk/stores/UltraDEX/page/02885511-9448-4D57-A25F-B3812F09FE2C?lp_asin=B071Z1B158",
    "seller_name": null,
    "landing_asin": "B071Z1B158"
  },
  "generated": "2026-10-21",
  "coverage": {
    "steps": [
      {
        "step": "keepa.token",
        "status": "ok",
        "tokens_left": 2,
        "per_minute": 1
      },
      {
        "step": "js.catalog.spellings",
        "status": "ok",
        "searched": [
          "UltraDEX",
          "Ultra DEX"
        ]
      },
      {
        "step": "js.catalog",
        "status": "ok",
        "asins": 84
      },
      {
        "step": "focus",
        "status": "ok",
        "live": 45,
        "hero_families": 6,
        "revenue_share": 0.85
      },
      {
        "step": "keepa.heroes",
        "status": "ok",
        "fetched": 13,
        "waited_min": 8.5
      },
      {
        "step": "images",
        "status": "skipped",
        "reason": "can't reach m.media-amazon.com (<urlopen error Tunnel connection failed: 403 Forbidden>); add it to Allowed domains"
      },
      {
        "step": "spapi.items",
        "status": "skipped",
        "reason": "SP-API not configured"
      },
      {
        "step": "keywords",
        "status": "ok",
        "heroes": 6,
        "keywords": 308
      },
      {
        "step": "js.sov",
        "status": "ok",
        "keywords": 13
      },
      {
        "step": "d4s.serp",
        "status": "ok",
        "keywords": 10
      },
      {
        "step": "ads.bids",
        "status": "skipped",
        "reason": "Ads API not configured; using Jungle Scout PPC bids"
      },
      {
        "step": "contacts",
        "status": "ok",
        "website": "https://ultradex.co.uk",
        "emails": 0
      }
    ],
    "budget": {
      "keepa": {
        "used": 10,
        "limit": 400.0
      },
      "junglescout": {
        "used": 21,
        "limit": 60.0
      },
      "dataforseo": {
        "used": 12.099999999999996,
        "limit": 40.0
      },
      "spapi": {
        "used": 0,
        "limit": 60.0
      },
      "ads": {
        "used": 0,
        "limit": 20.0
      },
      "apollo_search": {
        "used": 0,
        "limit": 10.0
      },
      "apollo_credits": {
        "used": 0,
        "limit": 3.0
      }
    },
    "collected_at": "2026-10-21T07:41:36.212585+00:00"
  },
  "focus": {
    "total_asins": 84,
    "live_asins": 45,
    "families": 30,
    "hero_families": 6,
    "hero_revenue_share": 0.85,
    "est_monthly_revenue": 99890
  },
  "heroes": [
    {
      "asin": "B071VT9KBZ",
      "parent_asin": "B0BGYRXB3B",
      "title": "UltraDEX Daily Oral Rinse, Mint 500 ml",
      "family_revenue_30d": 22344,
      "family_size": 3,
      "family_revenue_keepa": 28800,
      "units_30d": 2793,
      "price": 8.0,
      "list_price": 8.15,
      "sellers": 2,
      "buy_box_owner": "Amazon",
      "sold_by": "Amazon",
      "category": "Mouthwashes",
      "product_type": null,
      "rating": 4.6,
      "reviews": 1771,
      "content": {
        "score": 94,
        "checks": {
          "images": {
            "status": "good",
            "detail": "7 images"
          },
          "video": {
            "status": "good",
            "detail": "2 videos"
          },
          "a_plus": {
            "status": "good",
            "detail": "A+ with 1 modules"
          },
          "title": {
            "status": "warn",
            "detail": "38 chars"
          },
          "bullets": {
            "status": "good",
            "detail": "5 bullets"
          },
          "bullet_depth": {
            "status": "good",
            "detail": "avg 224 chars"
          },
          "rating": {
            "status": "good",
            "detail": "4.6\u2605"
          },
          "reviews": {
            "status": "good",
            "detail": "1778 reviews"
          }
        }
      },
      "mobile": {
        "score": 92,
        "checks": {
          "zoom": {
            "status": "good",
            "detail": "all 7 images zoomable (2000px+)"
          },
          "image_count": {
            "status": "good",
            "detail": "7 gallery images"
          },
          "video": {
            "status": "good",
            "detail": "2 brand video(s), shortest 12s"
          },
          "title_on_mobile": {
            "status": "good",
            "detail": "first 80 characters carry brand, product and size"
          },
          "bullets_on_mobile": {
            "status": "warn",
            "detail": "1 bullet(s) over 250 characters; mobile shows these collapsed"
          },
          "a_plus_on_mobile": {
            "status": "good",
            "detail": "7 A+ images with light, phone-friendly text"
          }
        }
      },
      "flags": [],
      "targets": [
        {
          "keyword": "alcohol free mouthwash",
          "tier": "category",
          "status": "push",
          "volume": 3097,
          "organic_rank": 43,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "alcohol-free mouthwash",
          "tier": "category",
          "status": "push",
          "volume": 677,
          "organic_rank": 51,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "nystatin oral suspension",
          "tier": "core",
          "status": "push",
          "volume": 660,
          "organic_rank": 14,
          "sponsored_rank": null,
          "cpc": null
        }
      ],
      "wasted_terms": [
        {
          "keyword": "euthymol",
          "volume": 3912,
          "sponsored_rank": 4,
          "reason": "unrelated to the product"
        }
      ],
      "sponsored_terms": 8,
      "mobile_sheet": null
    },
    {
      "asin": "B007Y5XCZE",
      "parent_asin": "B0GWQC292T",
      "title": "UltraDEX Daily Oral Rinse with Fluoride 500ml | Fresh Breath Mouthwash for Daily Oral Hygiene | Fluoride Mouth Rinse for Healthy Teeth & Gums",
      "family_revenue_30d": 19238,
      "family_size": 3,
      "family_revenue_keepa": 26807,
      "units_30d": 3381,
      "price": 5.69,
      "list_price": 8.0,
      "sellers": 12,
      "buy_box_owner": "Amazon",
      "sold_by": "Amazon",
      "category": "Mouthwashes",
      "product_type": null,
      "rating": 4.4,
      "reviews": 3639,
      "content": {
        "score": 100,
        "checks": {
          "images": {
            "status": "good",
            "detail": "7 images"
          },
          "video": {
            "status": "good",
            "detail": "4 videos"
          },
          "a_plus": {
            "status": "good",
            "detail": "A+ with 1 modules"
          },
          "title": {
            "status": "good",
            "detail": "141 chars"
          },
          "bullets": {
            "status": "good",
            "detail": "5 bullets"
          },
          "bullet_depth": {
            "status": "good",
            "detail": "avg 205 chars"
          },
          "rating": {
            "status": "good",
            "detail": "4.4\u2605"
          },
          "reviews": {
            "status": "good",
            "detail": "3641 reviews"
          }
        }
      },
      "mobile": {
        "score": 92,
        "checks": {
          "zoom": {
            "status": "warn",
            "detail": "all zoomable, but 6 under 1600px look soft when pinched"
          },
          "image_count": {
            "status": "good",
            "detail": "7 gallery images"
          },
          "video": {
            "status": "good",
            "detail": "3 brand video(s), shortest 12s"
          },
          "title_on_mobile": {
            "status": "good",
            "detail": "first 80 characters carry brand, product and size"
          },
          "bullets_on_mobile": {
            "status": "good",
            "detail": "5 bullets, first is 220 characters"
          },
          "a_plus_on_mobile": {
            "status": "good",
            "detail": "7 A+ images with light, phone-friendly text"
          }
        }
      },
      "flags": [],
      "targets": [
        {
          "keyword": "bad breath",
          "tier": "category",
          "status": "push",
          "volume": 73603,
          "organic_rank": 49,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "mouth wash",
          "tier": "category",
          "status": "push",
          "volume": 24719,
          "organic_rank": 39,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "mouthwash for gum disease",
          "tier": "long_tail",
          "status": "push",
          "volume": 7255,
          "organic_rank": 41,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "bad breath treatment for adults",
          "tier": "long_tail",
          "status": "push",
          "volume": 6721,
          "organic_rank": 35,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "therabreath mouthwash",
          "tier": "category",
          "status": "push",
          "volume": 4574,
          "organic_rank": 25,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "whitening mouthwash",
          "tier": "category",
          "status": "push",
          "volume": 4472,
          "organic_rank": 53,
          "sponsored_rank": null,
          "cpc": null
        }
      ],
      "wasted_terms": [
        {
          "keyword": "otrivine",
          "volume": 3481,
          "sponsored_rank": 1,
          "reason": "unrelated to the product"
        }
      ],
      "sponsored_terms": 10,
      "mobile_sheet": null
    },
    {
      "asin": "B007Y5XD3A",
      "parent_asin": "B0H3WXCLPT",
      "title": "UltraDEX Low-Abrasion Toothpaste 75Ml",
      "family_revenue_30d": 12867,
      "family_size": 2,
      "family_revenue_keepa": 5990,
      "units_30d": 1188,
      "price": 5.99,
      "list_price": 6.15,
      "sellers": 6,
      "buy_box_owner": "Amazon",
      "sold_by": "Amazon",
      "category": "Toothpastes",
      "product_type": null,
      "rating": 4.5,
      "reviews": 1518,
      "content": {
        "score": 94,
        "checks": {
          "images": {
            "status": "good",
            "detail": "8 images"
          },
          "video": {
            "status": "good",
            "detail": "1 video"
          },
          "a_plus": {
            "status": "good",
            "detail": "A+ with 1 modules"
          },
          "title": {
            "status": "warn",
            "detail": "37 chars"
          },
          "bullets": {
            "status": "good",
            "detail": "5 bullets"
          },
          "bullet_depth": {
            "status": "good",
            "detail": "avg 173 chars"
          },
          "rating": {
            "status": "good",
            "detail": "4.5\u2605"
          },
          "reviews": {
            "status": "good",
            "detail": "1518 reviews"
          }
        }
      },
      "mobile": {
        "score": 92,
        "checks": {
          "zoom": {
            "status": "warn",
            "detail": "all zoomable, but 2 under 1600px look soft when pinched"
          },
          "image_count": {
            "status": "good",
            "detail": "8 gallery images"
          },
          "video": {
            "status": "good",
            "detail": "1 brand video(s), shortest 62s"
          },
          "title_on_mobile": {
            "status": "good",
            "detail": "first 80 characters carry brand, product and size"
          },
          "bullets_on_mobile": {
            "status": "good",
            "detail": "5 bullets, first is 178 characters"
          },
          "a_plus_on_mobile": {
            "status": "good",
            "detail": "7 A+ images with light, phone-friendly text"
          }
        }
      },
      "flags": [],
      "targets": [
        {
          "keyword": "toothpaste",
          "tier": "category",
          "status": "push",
          "volume": 392821,
          "organic_rank": 47,
          "sponsored_rank": null,
          "cpc": 0.49
        },
        {
          "keyword": "whitening toothpaste",
          "tier": "category",
          "status": "push",
          "volume": 44232,
          "organic_rank": 48,
          "sponsored_rank": null,
          "cpc": 1.3
        },
        {
          "keyword": "curaprox toothpaste",
          "tier": "category",
          "status": "push",
          "volume": 3985,
          "organic_rank": 23,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "xylitol toothpaste",
          "tier": "category",
          "status": "push",
          "volume": 2985,
          "organic_rank": 60,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "oranurse unflavoured toothpaste",
          "tier": "category",
          "status": "push",
          "volume": 2849,
          "organic_rank": 51,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "gc tooth mousse",
          "tier": "category",
          "status": "push",
          "volume": 2714,
          "organic_rank": 51,
          "sponsored_rank": null,
          "cpc": 0.21
        }
      ],
      "wasted_terms": [
        {
          "keyword": "pearl drops",
          "volume": 1364,
          "sponsored_rank": 5,
          "reason": "unrelated to the product"
        },
        {
          "keyword": "detralex",
          "volume": 450,
          "sponsored_rank": 3,
          "reason": "unrelated to the product"
        }
      ],
      "sponsored_terms": 8,
      "mobile_sheet": null
    },
    {
      "asin": "B00HIXUCNC",
      "parent_asin": "B0BJ7VY23J",
      "title": "UltraDEX Fresh Breath Spray, 9 ml (Pack of 1)",
      "family_revenue_30d": 12786,
      "family_size": 3,
      "family_revenue_keepa": 16920,
      "units_30d": 5432,
      "price": 2.35,
      "list_price": 7.16,
      "sellers": 8,
      "buy_box_owner": "Amazon",
      "sold_by": "Amazon",
      "category": "Sprays",
      "product_type": null,
      "rating": 4.4,
      "reviews": 3999,
      "content": {
        "score": 88,
        "checks": {
          "images": {
            "status": "warn",
            "detail": "6 images"
          },
          "video": {
            "status": "good",
            "detail": "2 videos"
          },
          "a_plus": {
            "status": "good",
            "detail": "A+ with 1 modules"
          },
          "title": {
            "status": "warn",
            "detail": "45 chars"
          },
          "bullets": {
            "status": "good",
            "detail": "5 bullets"
          },
          "bullet_depth": {
            "status": "good",
            "detail": "avg 256 chars"
          },
          "rating": {
            "status": "good",
            "detail": "4.4\u2605"
          },
          "reviews": {
            "status": "good",
            "detail": "4007 reviews"
          }
        }
      },
      "mobile": {
        "score": 75,
        "checks": {
          "zoom": {
            "status": "warn",
            "detail": "all zoomable, but 1 under 1600px look soft when pinched"
          },
          "image_count": {
            "status": "warn",
            "detail": "6 gallery images"
          },
          "video": {
            "status": "good",
            "detail": "1 brand video(s), shortest 62s"
          },
          "title_on_mobile": {
            "status": "good",
            "detail": "first 80 characters carry brand, product and size"
          },
          "bullets_on_mobile": {
            "status": "warn",
            "detail": "1 bullet(s) over 250 characters; mobile shows these collapsed"
          },
          "a_plus_on_mobile": {
            "status": "good",
            "detail": "7 A+ images with light, phone-friendly text"
          }
        }
      },
      "flags": [],
      "targets": [
        {
          "keyword": "bad breath",
          "tier": "core",
          "status": "push",
          "volume": 73603,
          "organic_rank": 6,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "bad breath treatment for adults",
          "tier": "long_tail",
          "status": "push",
          "volume": 6721,
          "organic_rank": 9,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "dry mouth spray",
          "tier": "category",
          "status": "push",
          "volume": 4473,
          "organic_rank": 22,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "the breath co mouthwash",
          "tier": "long_tail",
          "status": "push",
          "volume": 4167,
          "organic_rank": 17,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "breath",
          "tier": "core",
          "status": "organic_top_unprotected",
          "volume": 2050,
          "organic_rank": 3,
          "sponsored_rank": null,
          "cpc": 0.23
        },
        {
          "keyword": "mouthwash for bad breath",
          "tier": "long_tail",
          "status": "push",
          "volume": 1929,
          "organic_rank": 16,
          "sponsored_rank": null,
          "cpc": null
        }
      ],
      "wasted_terms": [],
      "sponsored_terms": 19,
      "mobile_sheet": null
    },
    {
      "asin": "B071Z1B158",
      "parent_asin": "B0HGMDQGN2",
      "title": "Ultradex Daily Oral Rinse, 1000Ml",
      "family_revenue_30d": 9138,
      "family_size": 1,
      "family_revenue_keepa": 11380,
      "units_30d": 803,
      "price": 11.38,
      "list_price": 25.99,
      "sellers": 2,
      "buy_box_owner": "Amazon",
      "sold_by": "Amazon",
      "category": "Mouthwashes",
      "product_type": null,
      "rating": 4.7,
      "reviews": 721,
      "content": {
        "score": 94,
        "checks": {
          "images": {
            "status": "good",
            "detail": "7 images"
          },
          "video": {
            "status": "good",
            "detail": "2 videos"
          },
          "a_plus": {
            "status": "good",
            "detail": "A+ with 1 modules"
          },
          "title": {
            "status": "warn",
            "detail": "33 chars"
          },
          "bullets": {
            "status": "good",
            "detail": "5 bullets"
          },
          "bullet_depth": {
            "status": "good",
            "detail": "avg 212 chars"
          },
          "rating": {
            "status": "good",
            "detail": "4.7\u2605"
          },
          "reviews": {
            "status": "good",
            "detail": "725 reviews"
          }
        }
      },
      "mobile": {
        "score": 92,
        "checks": {
          "zoom": {
            "status": "good",
            "detail": "all 7 images zoomable (2000px+)"
          },
          "image_count": {
            "status": "good",
            "detail": "7 gallery images"
          },
          "video": {
            "status": "good",
            "detail": "2 brand video(s), shortest 12s"
          },
          "title_on_mobile": {
            "status": "good",
            "detail": "first 80 characters carry brand, product and size"
          },
          "bullets_on_mobile": {
            "status": "warn",
            "detail": "1 bullet(s) over 250 characters; mobile shows these collapsed"
          },
          "a_plus_on_mobile": {
            "status": "good",
            "detail": "7 A+ images with light, phone-friendly text"
          }
        }
      },
      "flags": [],
      "targets": [
        {
          "keyword": "oral thrush treatment for mouth and tongue",
          "tier": "long_tail",
          "status": "push",
          "volume": 653,
          "organic_rank": 29,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "antifungal mouthwash oral thrush",
          "tier": "long_tail",
          "status": "push",
          "volume": 450,
          "organic_rank": 26,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "beetakt oral mouthwash",
          "tier": "long_tail",
          "status": "push",
          "volume": 450,
          "organic_rank": 24,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "difflam oral rinse",
          "tier": "long_tail",
          "status": "push",
          "volume": 450,
          "organic_rank": 33,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "fluoride mouth rinse",
          "tier": "long_tail",
          "status": "push",
          "volume": 450,
          "organic_rank": 18,
          "sponsored_rank": null,
          "cpc": null
        }
      ],
      "wasted_terms": [],
      "sponsored_terms": 11,
      "mobile_sheet": null
    },
    {
      "asin": "B0BG66FF4T",
      "parent_asin": "B0GX213TNP",
      "title": "UltraDEX Low-Abrasion Toothpaste, Clinically Proven 12hr Bad Breath Treatment, Gentle & Non-Foaming, with Fluoride, Mint 6 X 75 ml, White",
      "family_revenue_30d": 8183,
      "family_size": 2,
      "family_revenue_keepa": 6678,
      "units_30d": 99,
      "price": 33.39,
      "list_price": 36.9,
      "sellers": 2,
      "buy_box_owner": "Amazon",
      "sold_by": "Amazon",
      "category": "Toothpastes",
      "product_type": null,
      "rating": 4.6,
      "reviews": 57,
      "content": {
        "score": 62,
        "checks": {
          "images": {
            "status": "warn",
            "detail": "5 images"
          },
          "video": {
            "status": "fail",
            "detail": "0 videos"
          },
          "a_plus": {
            "status": "fail",
            "detail": "no A+"
          },
          "title": {
            "status": "good",
            "detail": "137 chars"
          },
          "bullets": {
            "status": "good",
            "detail": "5 bullets"
          },
          "bullet_depth": {
            "status": "good",
            "detail": "avg 172 chars"
          },
          "rating": {
            "status": "good",
            "detail": "4.6\u2605"
          },
          "reviews": {
            "status": "warn",
            "detail": "58 reviews"
          }
        }
      },
      "mobile": {
        "score": 75,
        "checks": {
          "zoom": {
            "status": "good",
            "detail": "all 5 images zoomable (2000px+)"
          },
          "image_count": {
            "status": "warn",
            "detail": "5 gallery images"
          },
          "title_on_mobile": {
            "status": "warn",
            "detail": "cut off on mobile before the size/pack"
          },
          "bullets_on_mobile": {
            "status": "good",
            "detail": "5 bullets, first is 178 characters"
          }
        }
      },
      "flags": [],
      "targets": [
        {
          "keyword": "toothpastes",
          "tier": "category",
          "status": "push",
          "volume": 4893,
          "organic_rank": 45,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "extreme bad breath treatment",
          "tier": "long_tail",
          "status": "push",
          "volume": 480,
          "organic_rank": 39,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "ultradex fresh breath spray",
          "tier": "brand",
          "status": "push",
          "volume": 469,
          "organic_rank": 26,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "best toothpaste for bad breath",
          "tier": "long_tail",
          "status": "push",
          "volume": 464,
          "organic_rank": 5,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "bad breath toothpaste",
          "tier": "long_tail",
          "status": "push",
          "volume": 450,
          "organic_rank": 10,
          "sponsored_rank": null,
          "cpc": null
        },
        {
          "keyword": "oralieve ultra mild toothpaste",
          "tier": "long_tail",
          "status": "push",
          "volume": 450,
          "organic_rank": 40,
          "sponsored_rank": null,
          "cpc": null
        }
      ],
      "wasted_terms": [
        {
          "keyword": "guardium",
          "volume": 777,
          "sponsored_rank": 3,
          "reason": "unrelated to the product"
        }
      ],
      "sponsored_terms": 5,
      "mobile_sheet": null
    }
  ],
  "quick_wins": {
    "duplicates": [
      [
        {
          "asin": "B0BG676CYD",
          "title": "UltraDEX Fresh Breath Oral Spray 12 X 9 ml, White, 9 ml (Pack of 12)",
          "revenue_30d": 153436.2
        },
        {
          "asin": "B01MQ61GXT",
          "title": "Ultradex Fresh Breath Oral Spray 9ml (PACK OF 6)",
          "revenue_30d": 71.96
        },
        {
          "asin": "B01M2ADDW8",
          "title": "Ultradex Fresh Breath Oral Spray 9ml (PACK OF 4)",
          "revenue_30d": 49.95
        },
        {
          "asin": "B01M9GGSNS",
          "title": "Ultradex Fresh Breath Oral Spray 9ml (PACK OF 2)",
          "revenue_30d": 29.16
        }
      ],
      [
        {
          "asin": "B00HIXUCNC",
          "title": "UltraDEX Fresh Breath Spray, 9 ml (Pack of 1)",
          "revenue_30d": 12765.2
        },
        {
          "asin": "B086QXT8MR",
          "title": "UltraDEX Fresh Breath Spray 9ml - 2 Pack",
          "revenue_30d": 29.16
        }
      ],
      [
        {
          "asin": "B071Z1B158",
          "title": "Ultradex Daily Oral Rinse, 1000Ml",
          "revenue_30d": 9138.14
        },
        {
          "asin": "B013V6C9SK",
          "title": "ULTRADEX Rinse Daily Oral 500ML",
          "revenue_30d": 489.63
        },
        {
          "asin": "B016KXU6OK",
          "title": "6 x UltraDex Daily Oral Rinse 250ml",
          "revenue_30d": 143.6
        }
      ],
      [
        {
          "asin": "B007Y5XD3A",
          "title": "UltraDEX Low-Abrasion Toothpaste 75Ml",
          "revenue_30d": 7116.12
        },
        {
          "asin": "B00ZISXACE",
          "title": "6 x UltraDex Low-Abrasion Toothpaste 75ml",
          "revenue_30d": 398.32
        }
      ],
      [
        {
          "asin": "B00BIYO1B6",
          "title": "UltraDEX Whitening Toothpaste + Enamel Defense, Clinically Proven 12hr Bad Breat",
          "revenue_30d": 4452.0
        },
        {
          "asin": "B0BG63671K",
          "title": "UltraDEX Whitening Toothpaste + Enamel Defense, Clinically Proven 12hr Bad Breat",
          "revenue_30d": 297.0
        },
        {
          "asin": "B0H3KG5XV4",
          "title": "UltraDEX Whitening Toothpaste + Enamel Defense, Clinically Proven 12hr Bad Breat",
          "revenue_30d": 198.0
        }
      ],
      [
        {
          "asin": "B018469FIY",
          "title": "Ultradex Recalcifying & Whitening Toothpaste 75Ml - Pack of 6",
          "revenue_30d": 171.92
        },
        {
          "asin": "B00LI4KX7M",
          "title": "6 x UltraDex Recalcifying & Whitening Toothpaste 75ml",
          "revenue_30d": 132.24
        },
        {
          "asin": "B00DW7FY04",
          "title": "3X UltraDex Recalcifying & Whitening Toothpaste",
          "revenue_30d": 69.6
        }
      ]
    ],
    "clutter": [],
    "mixed_families": []
  },
  "asin_map": {
    "discovered": 84,
    "fetched": 13,
    "parents": 6,
    "categories": {
      "Health & Personal Care": 13
    },
    "asins": [
      {
        "asin": "B071VT9KBZ",
        "parent_asin": "B0BGYRXB3B",
        "title": "UltraDEX Daily Oral Rinse, Mint 500 ml",
        "price": 8.0,
        "rating": 4.6,
        "review_count": 1778,
        "monthly_sold": 3000,
        "sales_rank": 927.0,
        "listed_since": "2017-05-08",
        "root_category": "Health & Personal Care",
        "est_monthly_revenue": 24000
      },
      {
        "asin": "B007Y5XCZE",
        "parent_asin": "B0GWQC292T",
        "title": "UltraDEX Daily Oral Rinse with Fluoride 500ml | Fresh Breath Mouthwash for Daily Oral Hygiene | Fluoride Mouth Rinse for Healthy Teeth & Gums",
        "price": 5.69,
        "rating": 4.4,
        "review_count": 3641,
        "monthly_sold": 4000,
        "sales_rank": 732.0,
        "listed_since": "2012-06-02",
        "root_category": "Health & Personal Care",
        "est_monthly_revenue": 22760
      },
      {
        "asin": "B00HIXUCNC",
        "parent_asin": "B0BJ7VY23J",
        "title": "UltraDEX Fresh Breath Spray, 9 ml (Pack of 1)",
        "price": 2.35,
        "rating": 4.4,
        "review_count": 4007,
        "monthly_sold": 6000,
        "sales_rank": 358.0,
        "listed_since": "2012-07-13",
        "root_category": "Health & Personal Care",
        "est_monthly_revenue": 14100
      },
      {
        "asin": "B071Z1B158",
        "parent_asin": "B0HGMDQGN2",
        "title": "Ultradex Daily Oral Rinse, 1000Ml",
        "price": 11.38,
        "rating": 4.7,
        "review_count": 725,
        "monthly_sold": 1000,
        "sales_rank": 3603.0,
        "listed_since": "2017-05-08",
        "root_category": "Health & Personal Care",
        "est_monthly_revenue": 11380
      },
      {
        "asin": "B0BG66FF4T",
        "parent_asin": "B0GX213TNP",
        "title": "UltraDEX Low-Abrasion Toothpaste, Clinically Proven 12hr Bad Breath Treatment, Gentle & Non-Foaming, with Fluoride, Mint 6 X 75 ml, White",
        "price": 33.39,
        "rating": 4.6,
        "review_count": 58,
        "monthly_sold": 200,
        "sales_rank": 19536.0,
        "listed_since": "2012-07-01",
        "root_category": "Health & Personal Care",
        "est_monthly_revenue": 6678
      },
      {
        "asin": "B007Y5XD3A",
        "parent_asin": "B0H3WXCLPT",
        "title": "UltraDEX Low-Abrasion Toothpaste 75Ml",
        "price": 5.99,
        "rating": 4.5,
        "review_count": 1518,
        "monthly_sold": 1000,
        "sales_rank": 2458.0,
        "listed_since": "2012-06-02",
        "root_category": "Health & Personal Care",
        "est_monthly_revenue": 5990
      },
      {
        "asin": "B0BG63B8DT",
        "parent_asin": "B0BGYRXB3B",
        "title": "UltraDEX Daily Oral Rinse 500ml (Pack of 6) - Alcohol Free Mint Flavoured",
        "price": 48.0,
        "rating": 4.6,
        "review_count": 1778,
        "monthly_sold": 100,
        "sales_rank": 924.0,
        "listed_since": "2017-05-08",
        "root_category": "Health & Personal Care",
        "est_monthly_revenue": 4800
      },
      {
        "asin": "B0BGY8SGJS",
        "parent_asin": "B0GWQC292T",
        "title": "UltraDEX Daily Oral Rinse Original, 6 x 500ml, Clear",
        "price": 40.47,
        "rating": 4.4,
        "review_count": 3641,
        "monthly_sold": 100,
        "sales_rank": 732.0,
        "listed_since": "2012-07-01",
        "root_category": "Health & Personal Care",
        "est_monthly_revenue": 4047
      },
      {
        "asin": "B0BG676CYD",
        "parent_asin": "B0BJ7VY23J",
        "title": "UltraDEX Fresh Breath Oral Spray 12 X 9 ml, White, 9 ml (Pack of 12)",
        "price": 28.2,
        "rating": 4.4,
        "review_count": 4008,
        "monthly_sold": 100,
        "sales_rank": 358.0,
        "listed_since": "2012-07-01",
        "root_category": "Health & Personal Care",
        "est_monthly_revenue": 2820
      },
      {
        "asin": "B0GWQC292T",
        "parent_asin": "B0GWQC292T",
        "title": "Ultradex Daily Oral Rinse with Fluoride 500ml",
        "price": null,
        "rating": null,
        "review_count": null,
        "monthly_sold": null,
        "sales_rank": 732.0,
        "listed_since": "2026-04-10",
        "root_category": "Health & Personal Care",
        "est_monthly_revenue": null
      },
      {
        "asin": "B0BGYRXB3B",
        "parent_asin": "B0BGYRXB3B",
        "title": "UltraDEX Daily Oral Rinse, Mint 500 ml Clear",
        "price": null,
        "rating": null,
        "review_count": null,
        "monthly_sold": null,
        "sales_rank": 924.0,
        "listed_since": "2022-09-30",
        "root_category": "Health & Personal Care",
        "est_monthly_revenue": null
      },
      {
        "asin": "B0H3WXCLPT",
        "parent_asin": "B0H3WXCLPT",
        "title": "UltraDEX Low-Abrasion Toothpaste 75Ml",
        "price": null,
        "rating": null,
        "review_count": null,
        "monthly_sold": null,
        "sales_rank": 2458.0,
        "listed_since": "2026-06-03",
        "root_category": "Health & Personal Care",
        "est_monthly_revenue": null
      },
      {
        "asin": "B0GX213TNP",
        "parent_asin": "B0GX213TNP",
        "title": "UltraDEX Low-Abrasion Toothpaste 75Ml",
        "price": null,
        "rating": null,
        "review_count": null,
        "monthly_sold": null,
        "sales_rank": 19536.0,
        "listed_since": "2026-04-13",
        "root_category": "Health & Personal Care",
        "est_monthly_revenue": null
      }
    ]
  },
  "catalogue": {
    "asin_count": 13,
    "launches_by_quarter": {
      "2026-Q2": 3
    },
    "launches_last_12m": 3,
    "revenue_monthly_top_parents": {},
    "revenue_yoy_pct_last_3m": null,
    "est_monthly_revenue_keepa": 96575,
    "top3_revenue_share": 0.63,
    "bsr_trend_top_parents": {
      "median_bsr_now": 1194.5,
      "median_bsr_year_ago": 1756.0,
      "improved": true,
      "change_pct": -32
    },
    "reviews_gained_12m": 1460
  },
  "content": {
    "summary": {
      "avg_score_top_parents": 69,
      "share_under_7_images": 0.38,
      "share_no_video": 0.54,
      "share_no_aplus": 0.62,
      "share_under_5_bullets": 0.31,
      "share_rating_below_4_2": 0.0,
      "has_brand_store": true
    },
    "top_parents": [
      {
        "asin": "B0BGYRXB3B",
        "title": "UltraDEX Daily Oral Rinse, Mint 500 ml Clear",
        "score": 38,
        "checks": {
          "images": {
            "status": "warn",
            "detail": "6 images"
          },
          "video": {
            "status": "fail",
            "detail": "0 videos"
          },
          "a_plus": {
            "status": "fail",
            "detail": "no A+"
          },
          "title": {
            "status": "warn",
            "detail": "44 chars"
          },
          "bullets": {
            "status": "warn",
            "detail": "bullets not captured"
          },
          "bullet_depth": {
            "status": "warn",
            "detail": "not captured"
          },
          "rating": {
            "status": "warn",
            "detail": "\u2013\u2605"
          },
          "reviews": {
            "status": "warn",
            "detail": "0 reviews"
          }
        }
      },
      {
        "asin": "B007Y5XCZE",
        "title": "UltraDEX Daily Oral Rinse with Fluoride 500ml | Fresh Breath Mouthwash for Daily Oral Hygiene | Fluoride Mouth Rinse for Healthy Teeth & Gums",
        "score": 100,
        "checks": {
          "images": {
            "status": "good",
            "detail": "7 images"
          },
          "video": {
            "status": "good",
            "detail": "4 videos"
          },
          "a_plus": {
            "status": "good",
            "detail": "A+ with 1 modules"
          },
          "title": {
            "status": "good",
            "detail": "141 chars"
          },
          "bullets": {
            "status": "good",
            "detail": "5 bullets"
          },
          "bullet_depth": {
            "status": "good",
            "detail": "avg 205 chars"
          },
          "rating": {
            "status": "good",
            "detail": "4.4\u2605"
          },
          "reviews": {
            "status": "good",
            "detail": "3641 reviews"
          }
        }
      },
      {
        "asin": "B007Y5XD3A",
        "title": "UltraDEX Low-Abrasion Toothpaste 75Ml",
        "score": 94,
        "checks": {
          "images": {
            "status": "good",
            "detail": "8 images"
          },
          "video": {
            "status": "good",
            "detail": "1 video"
          },
          "a_plus": {
            "status": "good",
            "detail": "A+ with 1 modules"
          },
          "title": {
            "status": "warn",
            "detail": "37 chars"
          },
          "bullets": {
            "status": "good",
            "detail": "5 bullets"
          },
          "bullet_depth": {
            "status": "good",
            "detail": "avg 173 chars"
          },
          "rating": {
            "status": "good",
            "detail": "4.5\u2605"
          },
          "reviews": {
            "status": "good",
            "detail": "1518 reviews"
          }
        }
      },
      {
        "asin": "B0BG676CYD",
        "title": "UltraDEX Fresh Breath Oral Spray 12 X 9 ml, White, 9 ml (Pack of 12)",
        "score": 62,
        "checks": {
          "images": {
            "status": "warn",
            "detail": "6 images"
          },
          "video": {
            "status": "good",
            "detail": "1 video"
          },
          "a_plus": {
            "status": "fail",
            "detail": "no A+"
          },
          "title": {
            "status": "warn",
            "detail": "68 chars"
          },
          "bullets": {
            "status": "good",
            "detail": "5 bullets"
          },
          "bullet_depth": {
            "status": "fail",
            "detail": "avg 43 chars"
          },
          "rating": {
            "status": "good",
            "detail": "4.4\u2605"
          },
          "reviews": {
            "status": "good",
            "detail": "4008 reviews"
          }
        }
      },
      {
        "asin": "B071Z1B158",
        "title": "Ultradex Daily Oral Rinse, 1000Ml",
        "score": 94,
        "checks": {
          "images": {
            "status": "good",
            "detail": "7 images"
          },
          "video": {
            "status": "good",
            "detail": "2 videos"
          },
          "a_plus": {
            "status": "good",
            "detail": "A+ with 1 modules"
          },
          "title": {
            "status": "warn",
            "detail": "33 chars"
          },
          "bullets": {
            "status": "good",
            "detail": "5 bullets"
          },
          "bullet_depth": {
            "status": "good",
            "detail": "avg 212 chars"
          },
          "rating": {
            "status": "good",
            "detail": "4.7\u2605"
          },
          "reviews": {
            "status": "good",
            "detail": "725 reviews"
          }
        }
      },
      {
        "asin": "B0GX213TNP",
        "title": "UltraDEX Low-Abrasion Toothpaste 75Ml",
        "score": 25,
        "checks": {
          "images": {
            "status": "fail",
            "detail": "3 images"
          },
          "video": {
            "status": "fail",
            "detail": "0 videos"
          },
          "a_plus": {
            "status": "fail",
            "detail": "no A+"
          },
          "title": {
            "status": "warn",
            "detail": "37 chars"
          },
          "bullets": {
            "status": "warn",
            "detail": "3 bullets"
          },
          "bullet_depth": {
            "status": "fail",
            "detail": "avg 28 chars"
          },
          "rating": {
            "status": "warn",
            "detail": "\u2013\u2605"
          },
          "reviews": {
            "status": "warn",
            "detail": "0 reviews"
          }
        }
      }
    ],
    "variation_consolidation": []
  },
  "ads_observed": {
    "top30_keywords_with_sponsored_rank": 1,
    "top30_keywords": 30,
    "sponsored_coverage": 0.03,
    "est_monthly_spend_on_sampled_terms": {
      "low": 287,
      "high": 717
    },
    "note": "Estimate from share of voice x search volume x assumed ad click rate x CPC benchmark on sampled terms only."
  },
  "competitors": {
    "share_of_voice": [
      {
        "brand": "Colgate",
        "avg_sov": 0.178,
        "avg_sponsored_sov": 0.068,
        "keywords_present": 12,
        "is_prospect": false
      },
      {
        "brand": "Marvis",
        "avg_sov": 0.122,
        "avg_sponsored_sov": 0.058,
        "keywords_present": 10,
        "is_prospect": false
      },
      {
        "brand": "Corsodyl",
        "avg_sov": 0.11,
        "avg_sponsored_sov": 0.078,
        "keywords_present": 12,
        "is_prospect": false
      },
      {
        "brand": "Oral-B",
        "avg_sov": 0.102,
        "avg_sponsored_sov": 0.11,
        "keywords_present": 7,
        "is_prospect": false
      },
      {
        "brand": "Euthymol",
        "avg_sov": 0.087,
        "avg_sponsored_sov": 0.016,
        "keywords_present": 8,
        "is_prospect": false
      },
      {
        "brand": "Listerine",
        "avg_sov": 0.075,
        "avg_sponsored_sov": 0.088,
        "keywords_present": 5,
        "is_prospect": false
      },
      {
        "brand": "CB12",
        "avg_sov": 0.062,
        "avg_sponsored_sov": 0.064,
        "keywords_present": 5,
        "is_prospect": false
      },
      {
        "brand": "HISMILE",
        "avg_sov": 0.058,
        "avg_sponsored_sov": 0.104,
        "keywords_present": 9,
        "is_prospect": false
      },
      {
        "brand": "Waken",
        "avg_sov": 0.044,
        "avg_sponsored_sov": 0.09,
        "keywords_present": 11,
        "is_prospect": false
      },
      {
        "brand": "Sensodyne",
        "avg_sov": 0.043,
        "avg_sponsored_sov": 0.012,
        "keywords_present": 10,
        "is_prospect": false
      },
      {
        "brand": "The Breath Co.",
        "avg_sov": 0.032,
        "avg_sponsored_sov": 0.003,
        "keywords_present": 5,
        "is_prospect": false
      },
      {
        "brand": "Vitacrazy",
        "avg_sov": 0.02,
        "avg_sponsored_sov": 0.0,
        "keywords_present": 3,
        "is_prospect": false
      },
      {
        "brand": "BetterWhite",
        "avg_sov": 0.012,
        "avg_sponsored_sov": 0.015,
        "keywords_present": 4,
        "is_prospect": false
      },
      {
        "brand": "HealthAid",
        "avg_sov": 0.009,
        "avg_sponsored_sov": 0.0,
        "keywords_present": 1,
        "is_prospect": false
      },
      {
        "brand": "UltraDEX",
        "avg_sov": 0.007,
        "avg_sponsored_sov": 0.0,
        "keywords_present": 12,
        "is_prospect": true
      }
    ],
    "sov_change_vs_last_run": null,
    "brand_term_attackers": [
      {
        "keyword": "ultradex",
        "asin": "B00KKE8CC4",
        "brand_guess": "CB12 Mouthwash",
        "title": "CB12 Mouthwash Mint Alcohol Free for 12H Bad Breath Treatment 1 Litre | Chlorhexidine mout",
        "position": 4
      },
      {
        "keyword": "ultradex",
        "asin": "B00KKE8CC4",
        "brand_guess": "CB12 Mouthwash",
        "title": "CB12 Mouthwash Mint Alcohol Free for 12H Bad Breath Treatment 1 Litre | Chlorhexidine mout",
        "position": 50
      },
      {
        "keyword": "ultradex mouthwash",
        "asin": "B00KKE8CC4",
        "brand_guess": "CB12 Mouthwash",
        "title": "CB12 Mouthwash Mint Alcohol Free for 12H Bad Breath Treatment 1 Litre | Chlorhexidine mout",
        "position": 15
      },
      {
        "keyword": "ultradex mouthwash",
        "asin": "B01JZHYC1G",
        "brand_guess": "CB12 Whitening",
        "title": "CB12 Whitening Mouthwash Alcohol Free for 16H Bad Breath Treatment 250ml | Whitening chlor",
        "position": 50
      }
    ],
    "prospect_sponsored_on_own_brand": false,
    "positioning_page1": {
      "our_median_price": 4.7,
      "competitor_median_price": 7.16,
      "our_median_rating": 4.4,
      "competitor_median_rating": 4.6
    }
  },
  "strategy": {
    "keyword_map": [
      {
        "keyword": "toothpaste",
        "tier": "core",
        "volume": 392821,
        "organic_rank": 47,
        "sponsored_rank": null,
        "cpc": 0.49,
        "status": "push",
        "priority": 801676
      },
      {
        "keyword": "mouthwash",
        "tier": "core",
        "volume": 174132,
        "organic_rank": 15,
        "sponsored_rank": null,
        "cpc": 0.3,
        "status": "push",
        "priority": 580440
      },
      {
        "keyword": "bad breath",
        "tier": "core",
        "volume": 73603,
        "organic_rank": 6,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 73603
      },
      {
        "keyword": "whitening toothpaste",
        "tier": "core",
        "volume": 44232,
        "organic_rank": 48,
        "sponsored_rank": null,
        "cpc": 1.3,
        "status": "push",
        "priority": 34025
      },
      {
        "keyword": "toothpaste whitening",
        "tier": "core",
        "volume": 29758,
        "organic_rank": 124,
        "sponsored_rank": null,
        "cpc": 0.81,
        "status": "missing",
        "priority": 22043
      },
      {
        "keyword": "marvis toothpaste",
        "tier": "competitor",
        "volume": 23059,
        "organic_rank": 127,
        "sponsored_rank": null,
        "cpc": 0.18,
        "status": "missing",
        "priority": 20753
      },
      {
        "keyword": "mouth wash",
        "tier": "category",
        "volume": 24719,
        "organic_rank": 27,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 17303
      },
      {
        "keyword": "gc tooth mousse",
        "tier": "core",
        "volume": 2714,
        "organic_rank": 51,
        "sponsored_rank": null,
        "cpc": 0.21,
        "status": "push",
        "priority": 12924
      },
      {
        "keyword": "spray",
        "tier": "core",
        "volume": 4433,
        "organic_rank": 142,
        "sponsored_rank": null,
        "cpc": 0.22,
        "status": "missing",
        "priority": 12090
      },
      {
        "keyword": "tooth paste",
        "tier": "core",
        "volume": 11507,
        "organic_rank": 80,
        "sponsored_rank": null,
        "cpc": 0.66,
        "status": "missing",
        "priority": 10461
      },
      {
        "keyword": "marvis",
        "tier": "competitor",
        "volume": 6720,
        "organic_rank": 95,
        "sponsored_rank": null,
        "cpc": 0.15,
        "status": "missing",
        "priority": 6048
      },
      {
        "keyword": "corsodyl mouthwash",
        "tier": "competitor",
        "volume": 32741,
        "organic_rank": 115,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 5893
      },
      {
        "keyword": "toothpastes",
        "tier": "core",
        "volume": 4893,
        "organic_rank": 45,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 4893
      },
      {
        "keyword": "listerine mouthwash",
        "tier": "competitor",
        "volume": 25858,
        "organic_rank": 85,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 4654
      },
      {
        "keyword": "breath",
        "tier": "core",
        "volume": 2050,
        "organic_rank": 3,
        "sponsored_rank": null,
        "cpc": 0.23,
        "status": "organic_top_unprotected",
        "priority": 4457
      },
      {
        "keyword": "travel mouthwash",
        "tier": "core",
        "volume": 4362,
        "organic_rank": 12,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 4362
      },
      {
        "keyword": "kids mouthwash",
        "tier": "core",
        "volume": 4176,
        "organic_rank": 58,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 4176
      },
      {
        "keyword": "fluoride toothpaste",
        "tier": "core",
        "volume": 6833,
        "organic_rank": 63,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 4100
      },
      {
        "keyword": "corsodyl toothpaste",
        "tier": "competitor",
        "volume": 22162,
        "organic_rank": 122,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 3989
      },
      {
        "keyword": "curaprox toothpaste",
        "tier": "core",
        "volume": 3985,
        "organic_rank": 23,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 3985
      },
      {
        "keyword": "otrivine",
        "tier": "core",
        "volume": 3481,
        "organic_rank": null,
        "sponsored_rank": 1,
        "cpc": 0.35,
        "status": "sponsored_only",
        "priority": 3978
      },
      {
        "keyword": "mouth ulcer treatment",
        "tier": "category",
        "volume": 9214,
        "organic_rank": 130,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 3870
      },
      {
        "keyword": "mouthwash for gum disease",
        "tier": "long_tail",
        "volume": 7255,
        "organic_rank": 41,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 3628
      },
      {
        "keyword": "fresh breath",
        "tier": "core",
        "volume": 1380,
        "organic_rank": 2,
        "sponsored_rank": null,
        "cpc": 0.17,
        "status": "organic_top_unprotected",
        "priority": 3450
      },
      {
        "keyword": "oralieve",
        "tier": "category",
        "volume": 1675,
        "organic_rank": 32,
        "sponsored_rank": null,
        "cpc": 0.34,
        "status": "push",
        "priority": 3449
      },
      {
        "keyword": "bad breath treatment for adults",
        "tier": "long_tail",
        "volume": 6721,
        "organic_rank": 9,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 3360
      },
      {
        "keyword": "biotene",
        "tier": "category",
        "volume": 1914,
        "organic_rank": 45,
        "sponsored_rank": null,
        "cpc": 0.41,
        "status": "push",
        "priority": 3268
      },
      {
        "keyword": "therabreath mouthwash",
        "tier": "category",
        "volume": 4574,
        "organic_rank": 25,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 3202
      },
      {
        "keyword": "dry mouth spray",
        "tier": "category",
        "volume": 4473,
        "organic_rank": 22,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 3131
      },
      {
        "keyword": "whitening mouthwash",
        "tier": "category",
        "volume": 4472,
        "organic_rank": 37,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 3130
      },
      {
        "keyword": "toothpaste oral b",
        "tier": "core",
        "volume": 4627,
        "organic_rank": 122,
        "sponsored_rank": null,
        "cpc": 0.89,
        "status": "missing",
        "priority": 3119
      },
      {
        "keyword": "tooth mousse",
        "tier": "category",
        "volume": 1987,
        "organic_rank": 135,
        "sponsored_rank": null,
        "cpc": 0.27,
        "status": "missing",
        "priority": 3091
      },
      {
        "keyword": "biorepair toothpaste",
        "tier": "core",
        "volume": 5061,
        "organic_rank": 72,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 3037
      },
      {
        "keyword": "xylitol toothpaste",
        "tier": "core",
        "volume": 2985,
        "organic_rank": 60,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 2985
      },
      {
        "keyword": "antibacterial mouthwash",
        "tier": "category",
        "volume": 4169,
        "organic_rank": 30,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 2918
      },
      {
        "keyword": "oranurse unflavoured toothpaste",
        "tier": "core",
        "volume": 2849,
        "organic_rank": 51,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 2849
      },
      {
        "keyword": "zing toothpaste",
        "tier": "core",
        "volume": 4726,
        "organic_rank": 97,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 2836
      },
      {
        "keyword": "gum toothpaste",
        "tier": "core",
        "volume": 1774,
        "organic_rank": 104,
        "sponsored_rank": null,
        "cpc": 0.38,
        "status": "missing",
        "priority": 2801
      },
      {
        "keyword": "peroxyl mouthwash",
        "tier": "category",
        "volume": 3727,
        "organic_rank": 41,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 2609
      },
      {
        "keyword": "hydrogen peroxide mouthwash",
        "tier": "category",
        "volume": 3691,
        "organic_rank": 40,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 2584
      },
      {
        "keyword": "chlorhexidine mouthwash",
        "tier": "category",
        "volume": 3683,
        "organic_rank": 48,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 2578
      },
      {
        "keyword": "antiseptic mouthwash",
        "tier": "category",
        "volume": 3537,
        "organic_rank": 58,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 2476
      },
      {
        "keyword": "veneer toothpaste",
        "tier": "core",
        "volume": 2451,
        "organic_rank": 13,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 2451
      },
      {
        "keyword": "sls free toothpaste",
        "tier": "core",
        "volume": 3988,
        "organic_rank": 91,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 2393
      },
      {
        "keyword": "mouthwashes",
        "tier": "core",
        "volume": 2362,
        "organic_rank": 17,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 2362
      },
      {
        "keyword": "euthymol toothpaste",
        "tier": "competitor",
        "volume": 14550,
        "organic_rank": 141,
        "sponsored_rank": null,
        "cpc": 1.11,
        "status": "missing",
        "priority": 2359
      },
      {
        "keyword": "trycure whitening mouthwash",
        "tier": "core",
        "volume": 2358,
        "organic_rank": 20,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 2358
      },
      {
        "keyword": "duraphat 5000ppm fluoride toothpaste",
        "tier": "long_tail",
        "volume": 2090,
        "organic_rank": 64,
        "sponsored_rank": null,
        "cpc": 0.27,
        "status": "missing",
        "priority": 2322
      },
      {
        "keyword": "curasept mouthwash",
        "tier": "category",
        "volume": 3129,
        "organic_rank": 37,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 2190
      },
      {
        "keyword": "alcohol free mouthwash",
        "tier": "category",
        "volume": 3097,
        "organic_rank": 43,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 2168
      },
      {
        "keyword": "listerine strips",
        "tier": "competitor",
        "volume": 5926,
        "organic_rank": 7,
        "sponsored_rank": null,
        "cpc": 0.84,
        "status": "push",
        "priority": 2116
      },
      {
        "keyword": "pronamel toothpaste",
        "tier": "core",
        "volume": 3504,
        "organic_rank": 108,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 2102
      },
      {
        "keyword": "orajel",
        "tier": "category",
        "volume": 3003,
        "organic_rank": 42,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 2102
      },
      {
        "keyword": "the breath co mouthwash",
        "tier": "long_tail",
        "volume": 4167,
        "organic_rank": 17,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 2084
      },
      {
        "keyword": "daktarin oral gel",
        "tier": "core",
        "volume": 2034,
        "organic_rank": 14,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 2034
      },
      {
        "keyword": "aloe dent toothpaste",
        "tier": "core",
        "volume": 3245,
        "organic_rank": 96,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 1947
      },
      {
        "keyword": "dentyl mouthwash",
        "tier": "category",
        "volume": 2765,
        "organic_rank": 47,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1935
      },
      {
        "keyword": "biotene mouthwash",
        "tier": "category",
        "volume": 2758,
        "organic_rank": 29,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1931
      },
      {
        "keyword": "curasept",
        "tier": "category",
        "volume": 906,
        "organic_rank": 66,
        "sponsored_rank": null,
        "cpc": 0.18,
        "status": "missing",
        "priority": 1903
      },
      {
        "keyword": "mouthwash alcohol free",
        "tier": "category",
        "volume": 4205,
        "organic_rank": 61,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 1766
      },
      {
        "keyword": "breath strips",
        "tier": "core",
        "volume": 1447,
        "organic_rank": 7,
        "sponsored_rank": null,
        "cpc": 0.84,
        "status": "push",
        "priority": 1723
      },
      {
        "keyword": "steradent",
        "tier": "category",
        "volume": 4013,
        "organic_rank": 61,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 1685
      },
      {
        "keyword": "mouth ulcer treatment for adults",
        "tier": "long_tail",
        "volume": 3279,
        "organic_rank": 57,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1640
      },
      {
        "keyword": "curasept gel",
        "tier": "category",
        "volume": 568,
        "organic_rank": 37,
        "sponsored_rank": null,
        "cpc": 0.26,
        "status": "push",
        "priority": 1529
      },
      {
        "keyword": "high fluoride toothpaste",
        "tier": "core",
        "volume": 2477,
        "organic_rank": 75,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 1486
      },
      {
        "keyword": "dry mouth relief",
        "tier": "category",
        "volume": 3456,
        "organic_rank": 94,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 1452
      },
      {
        "keyword": "elmex toothpaste",
        "tier": "core",
        "volume": 2410,
        "organic_rank": 72,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 1446
      },
      {
        "keyword": "travel size mouthwash",
        "tier": "core",
        "volume": 1437,
        "organic_rank": 18,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1437
      },
      {
        "keyword": "biotene toothpaste",
        "tier": "core",
        "volume": 1391,
        "organic_rank": 33,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1391
      },
      {
        "keyword": "lumine organics mouthwash",
        "tier": "category",
        "volume": 1986,
        "organic_rank": 23,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1390
      },
      {
        "keyword": "gingivitis treatment",
        "tier": "category",
        "volume": 3293,
        "organic_rank": 79,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 1383
      },
      {
        "keyword": "oral hygiene products",
        "tier": "core",
        "volume": 1378,
        "organic_rank": 12,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1378
      },
      {
        "keyword": "toothpast",
        "tier": "core",
        "volume": 1070,
        "organic_rank": 66,
        "sponsored_rank": null,
        "cpc": 0.5,
        "status": "missing",
        "priority": 1284
      },
      {
        "keyword": "oral b mouthwash",
        "tier": "category",
        "volume": 1782,
        "organic_rank": 57,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1247
      },
      {
        "keyword": "gum disease mouthwash",
        "tier": "category",
        "volume": 1765,
        "organic_rank": 46,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1236
      },
      {
        "keyword": "the breath co",
        "tier": "core",
        "volume": 1225,
        "organic_rank": 15,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1225
      },
      {
        "keyword": "oranurse toothpaste",
        "tier": "core",
        "volume": 1218,
        "organic_rank": 58,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1218
      },
      {
        "keyword": "mouthwash travel size",
        "tier": "core",
        "volume": 1206,
        "organic_rank": 11,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1206
      },
      {
        "keyword": "hydrogen peroxide toothpaste",
        "tier": "core",
        "volume": 2005,
        "organic_rank": 79,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 1203
      },
      {
        "keyword": "gengigel mouthwash",
        "tier": "category",
        "volume": 1707,
        "organic_rank": 39,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1195
      },
      {
        "keyword": "euthymol",
        "tier": "competitor",
        "volume": 3912,
        "organic_rank": null,
        "sponsored_rank": 4,
        "cpc": 0.4,
        "status": "sponsored_only",
        "priority": 1174
      },
      {
        "keyword": "mouthwash whitening",
        "tier": "category",
        "volume": 1634,
        "organic_rank": 40,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1144
      },
      {
        "keyword": "oranurse",
        "tier": "core",
        "volume": 1135,
        "organic_rank": 54,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1135
      },
      {
        "keyword": "bioniq toothpaste",
        "tier": "core",
        "volume": 1869,
        "organic_rank": 134,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 1121
      },
      {
        "keyword": "hygiene",
        "tier": "core",
        "volume": 1119,
        "organic_rank": 12,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1119
      },
      {
        "keyword": "dcxc toothpaste whitening",
        "tier": "core",
        "volume": 1102,
        "organic_rank": 45,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1102
      },
      {
        "keyword": "mouth wash for gums disease",
        "tier": "long_tail",
        "volume": 2180,
        "organic_rank": 30,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 1090
      },
      {
        "keyword": "colgate mouthwash",
        "tier": "competitor",
        "volume": 5776,
        "organic_rank": 82,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 1040
      },
      {
        "keyword": "hygiene spray",
        "tier": "long_tail",
        "volume": 450,
        "organic_rank": 26,
        "sponsored_rank": null,
        "cpc": 0.23,
        "status": "push",
        "priority": 978
      },
      {
        "keyword": "oral hygiene",
        "tier": "core",
        "volume": 941,
        "organic_rank": 17,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 941
      },
      {
        "keyword": "teeth whitening mouthwash",
        "tier": "category",
        "volume": 1319,
        "organic_rank": 42,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 923
      },
      {
        "keyword": "fluorigard mouthwash",
        "tier": "core",
        "volume": 904,
        "organic_rank": 10,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 904
      },
      {
        "keyword": "travel mouthwash mini",
        "tier": "core",
        "volume": 896,
        "organic_rank": 8,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 896
      },
      {
        "keyword": "anti snoring spray",
        "tier": "category",
        "volume": 1242,
        "organic_rank": 51,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 869
      },
      {
        "keyword": "toothpaste travel size",
        "tier": "core",
        "volume": 1428,
        "organic_rank": 107,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 857
      },
      {
        "keyword": "therabreath",
        "tier": "category",
        "volume": 1216,
        "organic_rank": 34,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 851
      },
      {
        "keyword": "blanx toothpaste",
        "tier": "core",
        "volume": 850,
        "organic_rank": 50,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 850
      },
      {
        "keyword": "tepe toothpaste",
        "tier": "core",
        "volume": 838,
        "organic_rank": 19,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 838
      },
      {
        "keyword": "sls free toothpaste uk",
        "tier": "long_tail",
        "volume": 1613,
        "organic_rank": 44,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 806
      },
      {
        "keyword": "dental hygiene",
        "tier": "category",
        "volume": 1140,
        "organic_rank": 41,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 798
      },
      {
        "keyword": "composite bonding toothpaste",
        "tier": "core",
        "volume": 793,
        "organic_rank": 36,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 793
      },
      {
        "keyword": "mini mouthwash",
        "tier": "core",
        "volume": 2615,
        "organic_rank": 9,
        "sponsored_rank": 12,
        "cpc": null,
        "status": "sponsored_support",
        "priority": 784
      },
      {
        "keyword": "xylitol mouthwash",
        "tier": "category",
        "volume": 1102,
        "organic_rank": 28,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 771
      },
      {
        "keyword": "dentyl",
        "tier": "category",
        "volume": 1095,
        "organic_rank": 39,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 766
      },
      {
        "keyword": "cortisol mouthwash",
        "tier": "category",
        "volume": 1090,
        "organic_rank": 33,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 763
      },
      {
        "keyword": "fluoride mouthwash",
        "tier": "core",
        "volume": 2529,
        "organic_rank": 10,
        "sponsored_rank": 36,
        "cpc": null,
        "status": "sponsored_support",
        "priority": 759
      },
      {
        "keyword": "dry mouth mouthwash",
        "tier": "category",
        "volume": 1063,
        "organic_rank": 23,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 744
      },
      {
        "keyword": "difflam",
        "tier": "category",
        "volume": 1047,
        "organic_rank": 26,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 733
      },
      {
        "keyword": "unflavoured toothpaste",
        "tier": "core",
        "volume": 1209,
        "organic_rank": 86,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 725
      },
      {
        "keyword": "zing toothpaste whitening",
        "tier": "core",
        "volume": 1184,
        "organic_rank": 73,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 710
      },
      {
        "keyword": "closys mouthwash",
        "tier": "core",
        "volume": 707,
        "organic_rank": 9,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 707
      },
      {
        "keyword": "oralieve toothpaste",
        "tier": "core",
        "volume": 1177,
        "organic_rank": 81,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 706
      },
      {
        "keyword": "nil by mouth",
        "tier": "core",
        "volume": 1731,
        "organic_rank": null,
        "sponsored_rank": 1,
        "cpc": null,
        "status": "sponsored_only",
        "priority": 692
      },
      {
        "keyword": "gum disease",
        "tier": "category",
        "volume": 1641,
        "organic_rank": 105,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 689
      },
      {
        "keyword": "macleans toothpaste",
        "tier": "core",
        "volume": 1139,
        "organic_rank": 76,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 683
      },
      {
        "keyword": "probiotic mouth spray",
        "tier": "core",
        "volume": 662,
        "organic_rank": 6,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 662
      },
      {
        "keyword": "nystatin oral suspension",
        "tier": "core",
        "volume": 660,
        "organic_rank": 14,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 660
      },
      {
        "keyword": "hi smile mouthwash",
        "tier": "category",
        "volume": 938,
        "organic_rank": 32,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 657
      },
      {
        "keyword": "waken mouthwash",
        "tier": "competitor",
        "volume": 2179,
        "organic_rank": 27,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 654
      },
      {
        "keyword": "oral care",
        "tier": "category",
        "volume": 1071,
        "organic_rank": 34,
        "sponsored_rank": null,
        "cpc": 1.18,
        "status": "push",
        "priority": 635
      },
      {
        "keyword": "peroxyl",
        "tier": "core",
        "volume": 622,
        "organic_rank": 19,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 622
      },
      {
        "keyword": "dog mouthwash",
        "tier": "category",
        "volume": 1477,
        "organic_rank": 94,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 620
      },
      {
        "keyword": "fluoride free mouthwash",
        "tier": "category",
        "volume": 867,
        "organic_rank": 56,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 607
      },
      {
        "keyword": "breath mints",
        "tier": "core",
        "volume": 1502,
        "organic_rank": null,
        "sponsored_rank": 12,
        "cpc": null,
        "status": "sponsored_only",
        "priority": 601
      },
      {
        "keyword": "toothoaste",
        "tier": "core",
        "volume": 593,
        "organic_rank": 46,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 593
      },
      {
        "keyword": "denture toothpaste",
        "tier": "core",
        "volume": 583,
        "organic_rank": 51,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 583
      },
      {
        "keyword": "gengigel toothpaste",
        "tier": "core",
        "volume": 575,
        "organic_rank": 55,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 575
      },
      {
        "keyword": "sensitive mouthwash",
        "tier": "category",
        "volume": 798,
        "organic_rank": 60,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 559
      },
      {
        "keyword": "gingivitis mouthwash",
        "tier": "category",
        "volume": 795,
        "organic_rank": 41,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 556
      },
      {
        "keyword": "dr dent purple mouthwash",
        "tier": "long_tail",
        "volume": 1106,
        "organic_rank": 39,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 553
      },
      {
        "keyword": "act mouthwash",
        "tier": "core",
        "volume": 550,
        "organic_rank": 12,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 550
      },
      {
        "keyword": "difflam mouthwash",
        "tier": "category",
        "volume": 781,
        "organic_rank": 37,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 547
      },
      {
        "keyword": "oraldene mouthwash",
        "tier": "core",
        "volume": 1808,
        "organic_rank": 25,
        "sponsored_rank": 4,
        "cpc": null,
        "status": "sponsored_support",
        "priority": 542
      },
      {
        "keyword": "oral probiotics for bad breath",
        "tier": "long_tail",
        "volume": 1076,
        "organic_rank": 59,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 538
      },
      {
        "keyword": "mouth wash antibacterial",
        "tier": "core",
        "volume": 1753,
        "organic_rank": 26,
        "sponsored_rank": 9,
        "cpc": null,
        "status": "sponsored_support",
        "priority": 526
      },
      {
        "keyword": "oralb toothpaste",
        "tier": "core",
        "volume": 869,
        "organic_rank": 93,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 521
      },
      {
        "keyword": "antibacterial toothpaste",
        "tier": "core",
        "volume": 519,
        "organic_rank": 34,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 519
      },
      {
        "keyword": "mouth ulcer",
        "tier": "category",
        "volume": 1221,
        "organic_rank": 132,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 513
      },
      {
        "keyword": "wisdom chlorhexidine mouthwash",
        "tier": "category",
        "volume": 730,
        "organic_rank": 54,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 511
      },
      {
        "keyword": "janina toothpaste",
        "tier": "core",
        "volume": 506,
        "organic_rank": 44,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 506
      },
      {
        "keyword": "breath co",
        "tier": "core",
        "volume": 502,
        "organic_rank": 12,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 502
      },
      {
        "keyword": "pearl drops",
        "tier": "core",
        "volume": 1364,
        "organic_rank": null,
        "sponsored_rank": 5,
        "cpc": 1.09,
        "status": "sponsored_only",
        "priority": 501
      },
      {
        "keyword": "zinc toothpaste",
        "tier": "core",
        "volume": 500,
        "organic_rank": 46,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 500
      },
      {
        "keyword": "bleeding gums treatment",
        "tier": "category",
        "volume": 1185,
        "organic_rank": 69,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 498
      },
      {
        "keyword": "biomed mouthwash",
        "tier": "category",
        "volume": 702,
        "organic_rank": 56,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 491
      },
      {
        "keyword": "oral",
        "tier": "category",
        "volume": 624,
        "organic_rank": 34,
        "sponsored_rank": null,
        "cpc": 0.89,
        "status": "push",
        "priority": 491
      },
      {
        "keyword": "mouthwash for bad breath",
        "tier": "long_tail",
        "volume": 1929,
        "organic_rank": 3,
        "sponsored_rank": null,
        "cpc": null,
        "status": "organic_top_unprotected",
        "priority": 482
      },
      {
        "keyword": "tonsil stone mouthwash",
        "tier": "core",
        "volume": 1594,
        "organic_rank": 18,
        "sponsored_rank": 8,
        "cpc": null,
        "status": "sponsored_support",
        "priority": 478
      },
      {
        "keyword": "alcohol-free mouthwash",
        "tier": "category",
        "volume": 677,
        "organic_rank": 24,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 474
      },
      {
        "keyword": "tonsillitis treatment",
        "tier": "category",
        "volume": 676,
        "organic_rank": 53,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 473
      }
    ],
    "tiers": {
      "core": {
        "keywords": 89,
        "volume": 881211,
        "gaps": 69
      },
      "competitor": {
        "keywords": 43,
        "volume": 173738,
        "gaps": 39
      },
      "category": {
        "keywords": 70,
        "volume": 149529,
        "gaps": 69
      },
      "long_tail": {
        "keywords": 97,
        "volume": 76634,
        "gaps": 80
      },
      "brand": {
        "keywords": 9,
        "volume": 8250,
        "gaps": 0
      }
    },
    "focus_keywords": [
      {
        "keyword": "toothpaste",
        "tier": "core",
        "volume": 392821,
        "organic_rank": 47,
        "sponsored_rank": null,
        "cpc": 0.49,
        "status": "push",
        "priority": 801676
      },
      {
        "keyword": "mouthwash",
        "tier": "core",
        "volume": 174132,
        "organic_rank": 15,
        "sponsored_rank": null,
        "cpc": 0.3,
        "status": "push",
        "priority": 580440
      },
      {
        "keyword": "bad breath",
        "tier": "core",
        "volume": 73603,
        "organic_rank": 6,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 73603
      },
      {
        "keyword": "whitening toothpaste",
        "tier": "core",
        "volume": 44232,
        "organic_rank": 48,
        "sponsored_rank": null,
        "cpc": 1.3,
        "status": "push",
        "priority": 34025
      },
      {
        "keyword": "toothpaste whitening",
        "tier": "core",
        "volume": 29758,
        "organic_rank": 124,
        "sponsored_rank": null,
        "cpc": 0.81,
        "status": "missing",
        "priority": 22043
      },
      {
        "keyword": "mouth wash",
        "tier": "category",
        "volume": 24719,
        "organic_rank": 27,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 17303
      },
      {
        "keyword": "gc tooth mousse",
        "tier": "core",
        "volume": 2714,
        "organic_rank": 51,
        "sponsored_rank": null,
        "cpc": 0.21,
        "status": "push",
        "priority": 12924
      },
      {
        "keyword": "spray",
        "tier": "core",
        "volume": 4433,
        "organic_rank": 142,
        "sponsored_rank": null,
        "cpc": 0.22,
        "status": "missing",
        "priority": 12090
      },
      {
        "keyword": "tooth paste",
        "tier": "core",
        "volume": 11507,
        "organic_rank": 80,
        "sponsored_rank": null,
        "cpc": 0.66,
        "status": "missing",
        "priority": 10461
      },
      {
        "keyword": "toothpastes",
        "tier": "core",
        "volume": 4893,
        "organic_rank": 45,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 4893
      },
      {
        "keyword": "breath",
        "tier": "core",
        "volume": 2050,
        "organic_rank": 3,
        "sponsored_rank": null,
        "cpc": 0.23,
        "status": "organic_top_unprotected",
        "priority": 4457
      },
      {
        "keyword": "travel mouthwash",
        "tier": "core",
        "volume": 4362,
        "organic_rank": 12,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 4362
      },
      {
        "keyword": "kids mouthwash",
        "tier": "core",
        "volume": 4176,
        "organic_rank": 58,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 4176
      },
      {
        "keyword": "fluoride toothpaste",
        "tier": "core",
        "volume": 6833,
        "organic_rank": 63,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 4100
      },
      {
        "keyword": "curaprox toothpaste",
        "tier": "core",
        "volume": 3985,
        "organic_rank": 23,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 3985
      },
      {
        "keyword": "mouth ulcer treatment",
        "tier": "category",
        "volume": 9214,
        "organic_rank": 130,
        "sponsored_rank": null,
        "cpc": null,
        "status": "missing",
        "priority": 3870
      },
      {
        "keyword": "mouthwash for gum disease",
        "tier": "long_tail",
        "volume": 7255,
        "organic_rank": 41,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 3628
      },
      {
        "keyword": "fresh breath",
        "tier": "core",
        "volume": 1380,
        "organic_rank": 2,
        "sponsored_rank": null,
        "cpc": 0.17,
        "status": "organic_top_unprotected",
        "priority": 3450
      },
      {
        "keyword": "oralieve",
        "tier": "category",
        "volume": 1675,
        "organic_rank": 32,
        "sponsored_rank": null,
        "cpc": 0.34,
        "status": "push",
        "priority": 3449
      },
      {
        "keyword": "bad breath treatment for adults",
        "tier": "long_tail",
        "volume": 6721,
        "organic_rank": 9,
        "sponsored_rank": null,
        "cpc": null,
        "status": "push",
        "priority": 3360
      }
    ],
    "budget": {
      "monthly_by_tier": {
        "core": 8068,
        "category": 7
      },
      "monthly_by_ad_type": {
        "SP": 4844,
        "SB": 1615,
        "SBV": 1615,
        "SD (remarketing/retention)": 1425
      },
      "monthly_total": 9500,
      "assumptions": {
        "clicks_per_search": 0.12,
        "target_sponsored_sov": {
          "brand": 0.5,
          "core": 0.2,
          "category": 0.1,
          "long_tail": 0.15,
          "competitor": 0.05
        },
        "ad_type_split": {
          "brand": {
            "SP": 0.5,
            "SB": 0.5
          },
          "core": {
            "SP": 0.6,
            "SB": 0.2,
            "SBV": 0.2
          },
          "category": {
            "SP": 0.5,
            "SB": 0.25,
            "SBV": 0.25
          },
          "long_tail": {
            "SP": 1.0
          },
          "competitor": {
            "SP": 0.6,
            "SD": 0.4
          }
        },
        "retention_share": 0.15
      }
    },
    "repeat_signals": {
      "sns_share": 0.62,
      "multipack_share": 0.38,
      "consumable_category": true,
      "likelihood": "high"
    }
  },
  "amc_benchmark": {
    "category": "Health & Personal Care",
    "available": false
  },
  "job_ad_present": false
}
```

### `audits/ultradex-uk-2026-10-21/audit.html`

The rendered one-page audit (from `templates/audit.html` + `dataset.json` + `findings.json`). Published at https://claude.ai/artifact/TKhhwmpufa9XDryV2gj4rV

```html
<title>UltraDEX Amazon Audit</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,500;1,400&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
/* Layout: one reading column; the five recommendations lead, evidence sections follow in the order the email cites them. */
:root {
  --bg: #f6f1e7;
  --paper: #fffdf8;
  --ink: #1a1a18;
  --ink-soft: #4a4842;
  --muted: #7d7a72;
  --rule: #d9d2c3;
  --accent: #d85a30;
  --accent-soft: #f3d9cc;
  --bar: #4a4842;
  --s0: #d85a30; --s1: #2a78d6; --s2: #1baf7a; --s3: #c98500; --s4: #6250d6; --s5: #e87ba4;
  --good: #0a7d0a; --warn: #a86a00; --fail: #c03434;
  --serif: "Lora", Georgia, serif;
  --sans: "Inter", system-ui, -apple-system, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, Menlo, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #191815; --paper: #22201c; --ink: #f0ebe0; --ink-soft: #c9c3b6; --muted: #9a958a; --rule: #3a3731;
    --accent: #ea7a50; --accent-soft: #4a2a1d; --bar: #c9c3b6;
    --s0: #ea7a50; --s1: #3987e5; --s2: #199e70; --s3: #c98500; --s4: #9085e9; --s5: #d55181;
    --good: #3cc23c; --warn: #f0b03a; --fail: #ef6b6b;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #191815; --paper: #22201c; --ink: #f0ebe0; --ink-soft: #c9c3b6; --muted: #9a958a; --rule: #3a3731;
  --accent: #ea7a50; --accent-soft: #4a2a1d; --bar: #c9c3b6;
  --s0: #ea7a50; --s1: #3987e5; --s2: #199e70; --s3: #c98500; --s4: #9085e9; --s5: #d55181;
  --good: #3cc23c; --warn: #f0b03a; --fail: #ef6b6b;
  color-scheme: dark;
}
*, *::before, *::after { box-sizing: border-box; }
body { background: var(--bg); color: var(--ink); font: 400 16px/1.6 var(--sans); -webkit-font-smoothing: antialiased; }
.page { max-width: 980px; margin: 0 auto; padding-block: 40px 64px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 56px; }
a { color: inherit; text-decoration-color: var(--accent); text-underline-offset: 3px; }
h1, h2 { font-family: var(--serif); font-weight: 400; letter-spacing: -0.015em; text-wrap: balance; margin: 0; }
h1 { font-size: clamp(34px, 7vw, 56px); line-height: 1.1; }
h2 { font-size: clamp(26px, 4vw, 34px); line-height: 1.2; }
h3 { font-size: 17px; font-weight: 600; margin: 0; text-wrap: balance; }
p { margin: 0; max-width: 68ch; }
.eyebrow, .tag, .stat-label, th, .tick, small { font-family: var(--mono); }
.eyebrow { font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
section { display: grid; gap: 20px; min-width: 0; }
section > header { display: grid; gap: 8px; border-top: 1px solid var(--rule); padding-top: 24px; }

/* Hero */
.hero { display: grid; gap: 14px; }
.hero .meta { display: flex; flex-wrap: wrap; gap: 8px 18px; color: var(--ink-soft); font-family: var(--mono); font-size: 13px; }
.headline { font-family: var(--serif); font-style: italic; font-size: clamp(19px, 2.6vw, 23px); color: var(--ink-soft); max-width: 60ch; }

/* Recommendations: numbered because they are in priority order */
.points { list-style: none; counter-reset: pt; margin: 0; padding: 0; display: grid; gap: 14px; }
.point { counter-increment: pt; display: grid; grid-template-columns: 44px 1fr; gap: 12px; background: var(--paper);
  border: 1px solid var(--rule); border-radius: 14px; padding: 20px 20px 18px 16px; }
.point::before { content: counter(pt); font-family: var(--serif); font-size: 30px; line-height: 1; color: var(--accent); text-align: center; }
.point-body { display: grid; gap: 8px; min-width: 0; }
.tag { font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
.quote { border-left: 2px solid var(--accent); padding-left: 12px; color: var(--ink-soft); font-size: 15px; }
details summary { cursor: pointer; color: var(--ink-soft); font-size: 14px; }
details ul { margin: 8px 0 0; padding-left: 18px; color: var(--ink-soft); font-size: 14px; display: grid; gap: 4px; }

/* Stats */
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 1px; background: var(--rule);
  border: 1px solid var(--rule); border-radius: 14px; overflow: hidden; }
.stat { background: var(--paper); padding: 16px; display: grid; gap: 4px; align-content: start; }
.stat-label { font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }
.stat-value { font-family: var(--serif); font-size: 28px; line-height: 1.15; font-variant-numeric: tabular-nums; }
.stat-note { font-size: 13px; color: var(--muted); }

/* Charts */
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 24px; }
.two > * { min-width: 0; display: grid; gap: 10px; align-content: start; }
.chart { width: 100%; height: auto; display: block; }
.chart .bar { fill: var(--bar); }
.chart .bar:hover { fill: var(--accent); }
.chart .grid { stroke: var(--rule); stroke-dasharray: 2 4; }
.chart .axis { stroke: var(--muted); }
.chart .tick { fill: var(--muted); font-size: 11px; }
.empty { color: var(--muted); font-style: italic; }
.hbars { display: grid; gap: 8px; }
.hbar { display: grid; grid-template-columns: minmax(90px, 160px) 1fr 52px; gap: 10px; align-items: center; font-size: 14px; }
.hbar-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hbar-track { height: 10px; background: var(--rule); border-radius: 5px; overflow: hidden; }
.hbar-fill { display: block; height: 100%; background: var(--bar); border-radius: 0 4px 4px 0; }
.hbar.mine { font-weight: 600; }
.hbar.mine .hbar-fill { background: var(--accent); }
.hbar-value { text-align: right; font-variant-numeric: tabular-nums; color: var(--ink-soft); }
.stack { display: flex; gap: 2px; height: 18px; border-radius: 4px; overflow: hidden; }
.seg, .sw { background: var(--s0); }
.s1 { background: var(--s1); } .s2 { background: var(--s2); } .s3 { background: var(--s3); } .s4 { background: var(--s4); } .s5 { background: var(--s5); }
.legend { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 14px; }
.legend li { display: flex; align-items: center; gap: 6px; }
.legend small { color: var(--muted); }
.sw { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.budget-total { font-family: var(--serif); font-size: 26px; }

/* Tables */
.scroll { overflow-x: auto; border: 1px solid var(--rule); border-radius: 12px; background: var(--paper); }
table { border-collapse: collapse; width: 100%; font-size: 14px; font-variant-numeric: tabular-nums; }
th { font-size: 11px; font-weight: 500; letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted); text-align: left; }
th, td { padding: 9px 12px; border-bottom: 1px solid var(--rule); vertical-align: top; }
tbody tr:last-child > * { border-bottom: 0; }
td.num, th.num { text-align: right; }
table.content td { white-space: nowrap; }
table.content th[scope="row"] { text-transform: none; letter-spacing: 0; color: var(--ink); font-size: 13px; min-width: 180px; }
table.content th[scope="row"] small { display: block; color: var(--muted); font-family: var(--sans); white-space: normal; }
.chip { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 50%; font-size: 11px; font-weight: 700; color: var(--paper); }
.chip.good { background: var(--good); } .chip.warn { background: var(--warn); } .chip.fail { background: var(--fail); }
.kw-status { font-size: 13px; color: var(--ink-soft); }
.kw-status.push, .kw-status.brand_defence_gap { color: var(--accent); font-weight: 600; }
.attackers { padding-left: 18px; margin: 0; display: grid; gap: 6px; }
.attackers small { display: block; color: var(--muted); font-family: var(--sans); }
ul, ol { margin: 0; padding-left: 20px; display: grid; gap: 6px; }
.method { font-size: 14px; color: var(--ink-soft); display: grid; gap: 10px; }
footer { font-family: var(--mono); font-size: 12px; color: var(--muted); }
.heroes { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; }
.hero-card { background: var(--paper); border: 1px solid var(--rule); border-radius: 14px; padding: 18px;
  display: grid; gap: 12px; align-content: start; min-width: 0; }
.hero-card header { display: grid; gap: 4px; }
.hero-card header a { font-family: var(--mono); font-size: 12px; color: var(--muted); }
.hero-meta { font-size: 13px; color: var(--ink-soft); font-variant-numeric: tabular-nums; }
.hero-card h4 { margin: 0 0 4px; font-family: var(--mono); font-size: 11px; font-weight: 500; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--muted); }
.hero-card ul { padding-left: 0; list-style: none; font-size: 14px; gap: 4px; }
.hero-card ul small, .quick small { display: block; color: var(--muted); }
.hero-card p { font-size: 14px; }
.hero-card .action { font-weight: 600; border-left: 2px solid var(--accent); padding-left: 10px; }
.flags li { display: flex; gap: 8px; align-items: baseline; }
.flags li.verdict { display: block; font-style: italic; color: var(--ink-soft); }
.quick { font-size: 14px; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (max-width: 520px) { .point { grid-template-columns: 1fr; } .point::before { text-align: left; } .hbar { grid-template-columns: 96px 1fr 44px; } }
</style>

<main class="page">
  <div class="hero">
    <span class="eyebrow">Smart PPC · Amazon audit</span>
    <h1>UltraDEX</h1>
    <div class="meta"><span>amazon.co.uk</span><span>Prepared 2026-10-21</span></div>
    <p class="headline">UltraDEX&#x27;s listings are strong and well reviewed, but it advertises on almost none of its biggest searches, and a competitor is buying the ad slot on its own brand name.</p>
  </div>

  <section>
    <header><span class="eyebrow">Priorities</span><h2>What I would do first</h2></header>
    <ol class="points"><li class="point"><div class="point-body"><span class="tag">advertising</span><h3>Put ad support behind the big searches where UltraDEX already ranks</h3><p>Only 1 of the top 30 keywords across the best-sellers has an UltraDEX ad. The Fresh Breath Spray ranks #6 organically for &#x27;bad breath&#x27; (73.6k/mo) with no ad, and the rinses sit at #39 for &#x27;mouth wash&#x27; (24.7k/mo) and #49 for &#x27;bad breath&#x27;. Exact-match ads on these terms are the fastest visibility win.</p><details><summary>What we saw</summary><ul><li>Sponsored coverage: 1 of top 30 keywords (Jungle Scout keywords by ASIN)</li><li>bad breath: 73,603/mo; Spray organic #6, Fluoride Rinse organic #49, no sponsored rank</li><li>mouth wash: 24,719/mo; Fluoride Rinse organic #39, no sponsored rank</li><li>toothpaste: 392,821/mo; Low-Abrasion Toothpaste organic #47, no sponsored rank, CPC ~£0.49</li></ul></details></div></li><li class="point"><div class="point-body"><span class="tag">advertising</span><h3>Defend the UltraDEX brand searches from CB12</h3><p>CB12 Mouthwash takes a sponsored slot at #4 on &#x27;ultradex&#x27; and #15 on &#x27;ultradex mouthwash&#x27;, and UltraDEX runs no ads on its own name. Brand-term ads are cheap and keep loyal buyers from switching.</p><details><summary>What we saw</summary><ul><li>&#x27;ultradex&#x27;: CB12 Mouthwash sponsored at position 4 (DataForSEO, Amazon UK)</li><li>&#x27;ultradex mouthwash&#x27;: CB12 sponsored at position 15</li><li>No UltraDEX sponsored placement on either brand search</li></ul></details></div></li><li class="point"><div class="point-body"><span class="tag">catalogue</span><h3>Bring the multipacks into their product families</h3><p>Pack sizes are listed separately from their main products, e.g. the Fresh Breath Spray 12-pack, &#x27;6 x Daily Oral Rinse 250ml&#x27; and the toothpaste 6-packs. That splits reviews and sales rank across six sets of duplicate listings. Merging them into variation families pools both.</p><details><summary>What we saw</summary><ul><li>6 duplicate groups among live listings (title match, different parents)</li><li>e.g. B0BG676CYD (Spray 12-pack) separate from B00HIXUCNC (single)</li><li>e.g. B016KXU6OK &#x27;6 x UltraDex Daily Oral Rinse 250ml&#x27; separate from the rinse family</li></ul></details></div></li><li class="point"><div class="point-body"><span class="tag">content</span><h3>12hr Low-Abrasion Toothpaste: finish the listing</h3><p>This newer best-seller family (~£7–8k/mo, 57 reviews) has 5 images, no video and no A+, and its title cuts off on mobile before the pack size. Bringing it up to the standard of the rinses would help it convert.</p><details><summary>What we saw</summary><ul><li>B0BG66FF4T: 5 images, 0 videos, no A+ (Keepa)</li><li>Title cut off before the size in mobile search (first 80 characters)</li><li>57 reviews, 4.6★</li></ul></details></div></li></ol>
  </section>

  <section>
    <header><span class="eyebrow">Snapshot</span><h2>The business today</h2></header>
    <div class="stats"><div class="stat"><span class="stat-label">ASINs listed</span><span class="stat-value">84</span><span class="stat-note">45 live and selling</span></div><div class="stat"><span class="stat-label">Best-sellers</span><span class="stat-value">6</span><span class="stat-note">product families making 85% of revenue</span></div><div class="stat"><span class="stat-label">Est. monthly revenue</span><span class="stat-value">£99,890</span><span class="stat-note">Jungle Scout 30-day estimate</span></div><div class="stat"><span class="stat-label">Sponsored coverage</span><span class="stat-value">3%</span><span class="stat-note">of their top 30 keywords</span></div><div class="stat"><span class="stat-label">Mobile-ready best-sellers</span><span class="stat-value">6 of 6</span><span class="stat-note">zoom, video, title, bullets and A+ on a phone</span></div></div>
  </section>

  <section>
    <header><span class="eyebrow">Best-sellers</span><h2>Where the money is</h2>
      <p>The products below make most of the revenue, so every recommendation starts here.</p></header>
    <div class="heroes"><article class="hero-card"><header><a href="https://www.amazon.co.uk/dp/B071VT9KBZ">B071VT9KBZ</a><h3>UltraDEX Daily Oral Rinse, Mint 500 ml</h3><span class="hero-meta">£22,344/mo · 2,793 units · £8.00 · 4.6★ (1,771)</span></header><p class="action">Add ads on &#x27;alcohol free mouthwash&#x27; (3.1k/mo, organic #43).</p><div><h4>Push</h4><ul><li>“alcohol free mouthwash” <small>3,097/mo · organic #43</small></li><li>“alcohol-free mouthwash” <small>677/mo · organic #51</small></li><li>“nystatin oral suspension” <small>660/mo · organic #14</small></li></ul></div><div><h4>Cut</h4><p>“euthymol”</p></div><div><h4>Mobile · 92/100</h4><ul class="flags"><li><span class="chip good" title="Good">✓</span> Zoom: all 7 images zoomable (2000px+)</li><li><span class="chip good" title="Good">✓</span> Images: 7 gallery images</li><li><span class="chip good" title="Good">✓</span> Video: 2 brand video(s), shortest 12s</li><li><span class="chip good" title="Good">✓</span> Title in search: first 80 characters carry brand, product and size</li><li><span class="chip warn" title="Needs work">!</span> Bullets: 1 bullet(s) over 250 characters; mobile shows these collapsed</li><li><span class="chip good" title="Good">✓</span> A+ on a phone: 7 A+ images with light, phone-friendly text</li></ul></div></article><article class="hero-card"><header><a href="https://www.amazon.co.uk/dp/B007Y5XCZE">B007Y5XCZE</a><h3>UltraDEX Daily Oral Rinse with Fluoride 500ml | Fresh Breath Mouthwash for Daily Oral Hygi</h3><span class="hero-meta">£19,238/mo · 3,381 units · £5.69 · 4.4★ (3,639)</span></header><p class="action">Exact-match ads on &#x27;mouth wash&#x27; and &#x27;bad breath&#x27;; drop &#x27;otrivine&#x27; (sponsored #1, unrelated).</p><div><h4>Push</h4><ul><li>“bad breath” <small>73,603/mo · organic #49</small></li><li>“mouth wash” <small>24,719/mo · organic #39</small></li><li>“mouthwash for gum disease” <small>7,255/mo · organic #41</small></li></ul></div><div><h4>Cut</h4><p>“otrivine”</p></div><div><h4>Mobile · 92/100</h4><ul class="flags"><li><span class="chip warn" title="Needs work">!</span> Zoom: all zoomable, but 6 under 1600px look soft when pinched</li><li><span class="chip good" title="Good">✓</span> Images: 7 gallery images</li><li><span class="chip good" title="Good">✓</span> Video: 3 brand video(s), shortest 12s</li><li><span class="chip good" title="Good">✓</span> Title in search: first 80 characters carry brand, product and size</li><li><span class="chip good" title="Good">✓</span> Bullets: 5 bullets, first is 220 characters</li><li><span class="chip good" title="Good">✓</span> A+ on a phone: 7 A+ images with light, phone-friendly text</li></ul></div></article><article class="hero-card"><header><a href="https://www.amazon.co.uk/dp/B007Y5XD3A">B007Y5XD3A</a><h3>UltraDEX Low-Abrasion Toothpaste 75Ml</h3><span class="hero-meta">£12,867/mo · 1,188 units · £5.99 · 4.5★ (1,518)</span></header><p class="action">Test ads on &#x27;toothpaste&#x27; and &#x27;whitening toothpaste&#x27;, where it ranks #47–48 with no ad support.</p><div><h4>Push</h4><ul><li>“toothpaste” <small>392,821/mo · organic #47 · £0.49 CPC</small></li><li>“whitening toothpaste” <small>44,232/mo · organic #48 · £1.30 CPC</small></li><li>“curaprox toothpaste” <small>3,985/mo · organic #23</small></li></ul></div><div><h4>Cut</h4><p>“pearl drops”, “detralex”</p></div><div><h4>Mobile · 92/100</h4><ul class="flags"><li><span class="chip warn" title="Needs work">!</span> Zoom: all zoomable, but 2 under 1600px look soft when pinched</li><li><span class="chip good" title="Good">✓</span> Images: 8 gallery images</li><li><span class="chip good" title="Good">✓</span> Video: 1 brand video(s), shortest 62s</li><li><span class="chip good" title="Good">✓</span> Title in search: first 80 characters carry brand, product and size</li><li><span class="chip good" title="Good">✓</span> Bullets: 5 bullets, first is 178 characters</li><li><span class="chip good" title="Good">✓</span> A+ on a phone: 7 A+ images with light, phone-friendly text</li></ul></div></article><article class="hero-card"><header><a href="https://www.amazon.co.uk/dp/B00HIXUCNC">B00HIXUCNC</a><h3>UltraDEX Fresh Breath Spray, 9 ml (Pack of 1)</h3><span class="hero-meta">£12,786/mo · 5,432 units · £2.35 · 4.4★ (3,999)</span></header><p class="action">Back the #6 organic rank on &#x27;bad breath&#x27; with ads, and add a 7th gallery image.</p><div><h4>Push</h4><ul><li>“bad breath” <small>73,603/mo · organic #6</small></li><li>“bad breath treatment for adults” <small>6,721/mo · organic #9</small></li><li>“dry mouth spray” <small>4,473/mo · organic #22</small></li></ul></div><div><h4>Mobile · 75/100</h4><ul class="flags"><li><span class="chip warn" title="Needs work">!</span> Zoom: all zoomable, but 1 under 1600px look soft when pinched</li><li><span class="chip warn" title="Needs work">!</span> Images: 6 gallery images</li><li><span class="chip good" title="Good">✓</span> Video: 1 brand video(s), shortest 62s</li><li><span class="chip good" title="Good">✓</span> Title in search: first 80 characters carry brand, product and size</li><li><span class="chip warn" title="Needs work">!</span> Bullets: 1 bullet(s) over 250 characters; mobile shows these collapsed</li><li><span class="chip good" title="Good">✓</span> A+ on a phone: 7 A+ images with light, phone-friendly text</li></ul></div></article><article class="hero-card"><header><a href="https://www.amazon.co.uk/dp/B071Z1B158">B071Z1B158</a><h3>Ultradex Daily Oral Rinse, 1000Ml</h3><span class="hero-meta">£9,138/mo · 803 units · £11.38 · 4.7★ (721)</span></header><p class="action">Fold the 250ml 6-pack and 1L into the rinse families; add ads on &#x27;fluoride mouth rinse&#x27;.</p><div><h4>Push</h4><ul><li>“oral thrush treatment for mouth and tongue” <small>653/mo · organic #29</small></li><li>“antifungal mouthwash oral thrush” <small>450/mo · organic #26</small></li><li>“beetakt oral mouthwash” <small>450/mo · organic #24</small></li></ul></div><div><h4>Mobile · 92/100</h4><ul class="flags"><li><span class="chip good" title="Good">✓</span> Zoom: all 7 images zoomable (2000px+)</li><li><span class="chip good" title="Good">✓</span> Images: 7 gallery images</li><li><span class="chip good" title="Good">✓</span> Video: 2 brand video(s), shortest 12s</li><li><span class="chip good" title="Good">✓</span> Title in search: first 80 characters carry brand, product and size</li><li><span class="chip warn" title="Needs work">!</span> Bullets: 1 bullet(s) over 250 characters; mobile shows these collapsed</li><li><span class="chip good" title="Good">✓</span> A+ on a phone: 7 A+ images with light, phone-friendly text</li></ul></div></article><article class="hero-card"><header><a href="https://www.amazon.co.uk/dp/B0BG66FF4T">B0BG66FF4T</a><h3>UltraDEX Low-Abrasion Toothpaste, Clinically Proven 12hr Bad Breath Treatment, Gentle &amp; No</h3><span class="hero-meta">£8,183/mo · 99 units · £33.39 · 4.6★ (57)</span></header><p class="action">Add video and A+, a 6th and 7th image, and move the pack size into the first 80 characters of the title.</p><div><h4>Push</h4><ul><li>“toothpastes” <small>4,893/mo · organic #45</small></li><li>“extreme bad breath treatment” <small>480/mo · organic #39</small></li><li>“ultradex fresh breath spray” <small>469/mo · organic #26</small></li></ul></div><div><h4>Cut</h4><p>“guardium”</p></div><div><h4>Mobile · 75/100</h4><ul class="flags"><li><span class="chip good" title="Good">✓</span> Zoom: all 5 images zoomable (2000px+)</li><li><span class="chip warn" title="Needs work">!</span> Images: 5 gallery images</li><li><span class="chip warn" title="Needs work">!</span> Title in search: cut off on mobile before the size/pack</li><li><span class="chip good" title="Good">✓</span> Bullets: 5 bullets, first is 178 characters</li></ul></div></article></div>
  </section>

  <section>
    <header><span class="eyebrow">Quick wins</span><h2>Catalogue tidy-up</h2></header>
    <ul class="quick"><li>Duplicate listings: B0BG676CYD / B01MQ61GXT / B01M2ADDW8 / B01M9GGSNS <small>UltraDEX Fresh Breath Oral Spray 12 X 9 ml, White, 9 ml (Pack of 12)</small></li><li>Duplicate listings: B00HIXUCNC / B086QXT8MR <small>UltraDEX Fresh Breath Spray, 9 ml (Pack of 1)</small></li><li>Duplicate listings: B071Z1B158 / B013V6C9SK / B016KXU6OK <small>Ultradex Daily Oral Rinse, 1000Ml</small></li><li>Duplicate listings: B007Y5XD3A / B00ZISXACE <small>UltraDEX Low-Abrasion Toothpaste 75Ml</small></li><li>Duplicate listings: B00BIYO1B6 / B0BG63671K / B0H3KG5XV4 <small>UltraDEX Whitening Toothpaste + Enamel Defense, Clinically Proven 12hr Bad Breat</small></li><li>Duplicate listings: B018469FIY / B00LI4KX7M / B00DW7FY04 <small>Ultradex Recalcifying &amp; Whitening Toothpaste 75Ml - Pack of 6</small></li></ul>
  </section>

  <section>
    <header><span class="eyebrow">Listings</span><h2>Content on the best-sellers</h2><p>The rinses and the spray are well built for mobile (2000px zoomable images, brand videos, phone-friendly A+). The newer 12hr toothpaste is the gap.</p></header>
    <div class="scroll"><table class="content"><thead><tr><th>Listing</th><th>Score</th><th>Images</th><th>Video</th><th>A Plus</th><th>Title</th><th>Bullets</th><th>Bullet Depth</th><th>Rating</th><th>Reviews</th></tr></thead><tbody><tr><th scope="row"><a href="https://www.amazon.co.uk/dp/B0BGYRXB3B">B0BGYRXB3B</a><small>UltraDEX Daily Oral Rinse, Mint 500 ml Clear</small></th><td class="num">38</td><td><span class="chip warn" title="Needs work">!</span> 6 images</td><td><span class="chip fail" title="Missing">✕</span> 0 videos</td><td><span class="chip fail" title="Missing">✕</span> no A+</td><td><span class="chip warn" title="Needs work">!</span> 44 chars</td><td><span class="chip warn" title="Needs work">!</span> bullets not captured</td><td><span class="chip warn" title="Needs work">!</span> not captured</td><td><span class="chip warn" title="Needs work">!</span> –★</td><td><span class="chip warn" title="Needs work">!</span> 0 reviews</td></tr><tr><th scope="row"><a href="https://www.amazon.co.uk/dp/B007Y5XCZE">B007Y5XCZE</a><small>UltraDEX Daily Oral Rinse with Fluoride 500ml | Fresh Breath</small></th><td class="num">100</td><td><span class="chip good" title="Good">✓</span> 7 images</td><td><span class="chip good" title="Good">✓</span> 4 videos</td><td><span class="chip good" title="Good">✓</span> A+ with 1 modules</td><td><span class="chip good" title="Good">✓</span> 141 chars</td><td><span class="chip good" title="Good">✓</span> 5 bullets</td><td><span class="chip good" title="Good">✓</span> avg 205 chars</td><td><span class="chip good" title="Good">✓</span> 4.4★</td><td><span class="chip good" title="Good">✓</span> 3641 reviews</td></tr><tr><th scope="row"><a href="https://www.amazon.co.uk/dp/B007Y5XD3A">B007Y5XD3A</a><small>UltraDEX Low-Abrasion Toothpaste 75Ml</small></th><td class="num">94</td><td><span class="chip good" title="Good">✓</span> 8 images</td><td><span class="chip good" title="Good">✓</span> 1 video</td><td><span class="chip good" title="Good">✓</span> A+ with 1 modules</td><td><span class="chip warn" title="Needs work">!</span> 37 chars</td><td><span class="chip good" title="Good">✓</span> 5 bullets</td><td><span class="chip good" title="Good">✓</span> avg 173 chars</td><td><span class="chip good" title="Good">✓</span> 4.5★</td><td><span class="chip good" title="Good">✓</span> 1518 reviews</td></tr><tr><th scope="row"><a href="https://www.amazon.co.uk/dp/B0BG676CYD">B0BG676CYD</a><small>UltraDEX Fresh Breath Oral Spray 12 X 9 ml, White, 9 ml (Pac</small></th><td class="num">62</td><td><span class="chip warn" title="Needs work">!</span> 6 images</td><td><span class="chip good" title="Good">✓</span> 1 video</td><td><span class="chip fail" title="Missing">✕</span> no A+</td><td><span class="chip warn" title="Needs work">!</span> 68 chars</td><td><span class="chip good" title="Good">✓</span> 5 bullets</td><td><span class="chip fail" title="Missing">✕</span> avg 43 chars</td><td><span class="chip good" title="Good">✓</span> 4.4★</td><td><span class="chip good" title="Good">✓</span> 4008 reviews</td></tr><tr><th scope="row"><a href="https://www.amazon.co.uk/dp/B071Z1B158">B071Z1B158</a><small>Ultradex Daily Oral Rinse, 1000Ml</small></th><td class="num">94</td><td><span class="chip good" title="Good">✓</span> 7 images</td><td><span class="chip good" title="Good">✓</span> 2 videos</td><td><span class="chip good" title="Good">✓</span> A+ with 1 modules</td><td><span class="chip warn" title="Needs work">!</span> 33 chars</td><td><span class="chip good" title="Good">✓</span> 5 bullets</td><td><span class="chip good" title="Good">✓</span> avg 212 chars</td><td><span class="chip good" title="Good">✓</span> 4.7★</td><td><span class="chip good" title="Good">✓</span> 725 reviews</td></tr><tr><th scope="row"><a href="https://www.amazon.co.uk/dp/B0GX213TNP">B0GX213TNP</a><small>UltraDEX Low-Abrasion Toothpaste 75Ml</small></th><td class="num">25</td><td><span class="chip fail" title="Missing">✕</span> 3 images</td><td><span class="chip fail" title="Missing">✕</span> 0 videos</td><td><span class="chip fail" title="Missing">✕</span> no A+</td><td><span class="chip warn" title="Needs work">!</span> 37 chars</td><td><span class="chip warn" title="Needs work">!</span> 3 bullets</td><td><span class="chip fail" title="Missing">✕</span> avg 28 chars</td><td><span class="chip warn" title="Needs work">!</span> –★</td><td><span class="chip warn" title="Needs work">!</span> 0 reviews</td></tr></tbody></table></div>
  </section>

  <section>
    <header><span class="eyebrow">Advertising</span><h2>Keyword map and where to spend</h2><p>UltraDEX is almost absent from paid search on its biggest terms. Defend the brand name first, then add exact-match ads where products already rank on page 1–3 (&#x27;bad breath&#x27;, &#x27;mouth wash&#x27;, &#x27;toothpaste&#x27;).</p></header>
    <div class="two">
      <div><h3>Keywords by tier</h3><div class="scroll"><table><thead><tr><th>Tier</th><th class="num">Keywords</th><th class="num">Searches/mo</th><th class="num">Gaps</th></tr></thead><tbody><tr><td>Core</td><td class="num">89</td><td class="num">881,211</td><td class="num">69</td></tr><tr><td>Competitor</td><td class="num">43</td><td class="num">173,738</td><td class="num">39</td></tr><tr><td>Category</td><td class="num">70</td><td class="num">149,529</td><td class="num">69</td></tr><tr><td>Long-tail</td><td class="num">97</td><td class="num">76,634</td><td class="num">80</td></tr><tr><td>Brand</td><td class="num">9</td><td class="num">8,250</td><td class="num">0</td></tr></tbody></table></div></div>
      <div><h3>Indicative monthly budget</h3><span class="budget-total">£9,500</span><div class="stack"><span class="seg s0" style="flex:4844" title="SP: £4,844"></span><span class="seg s1" style="flex:1615" title="SB: £1,615"></span><span class="seg s2" style="flex:1615" title="SBV: £1,615"></span><span class="seg s3" style="flex:1425" title="SD (remarketing/retention): £1,425"></span></div><ul class="legend"><li><span class="sw s0"></span>SP <b>£4,844</b> <small>51%</small></li><li><span class="sw s1"></span>SB <b>£1,615</b> <small>17%</small></li><li><span class="sw s2"></span>SBV <b>£1,615</b> <small>17%</small></li><li><span class="sw s3"></span>SD (remarketing/retention) <b>£1,425</b> <small>15%</small></li></ul></div>
    </div>
    <h3>Focus keywords</h3>
    <div class="scroll"><table><thead><tr><th>Keyword</th><th>Tier</th><th class="num">Searches/mo</th><th class="num">Organic</th><th class="num">Sponsored</th><th class="num">CPC</th><th>Status</th></tr></thead><tbody><tr><td>toothpaste</td><td>Core</td><td class="num">392,821</td><td class="num">47</td><td class="num">–</td><td class="num">£0.49</td><td><span class="kw-status push">Ranks page 1–2, no ads: push to top</span></td></tr><tr><td>mouthwash</td><td>Core</td><td class="num">174,132</td><td class="num">15</td><td class="num">–</td><td class="num">£0.30</td><td><span class="kw-status push">Ranks page 1–2, no ads: push to top</span></td></tr><tr><td>bad breath</td><td>Core</td><td class="num">73,603</td><td class="num">6</td><td class="num">–</td><td class="num">–</td><td><span class="kw-status push">Ranks page 1–2, no ads: push to top</span></td></tr><tr><td>whitening toothpaste</td><td>Core</td><td class="num">44,232</td><td class="num">48</td><td class="num">–</td><td class="num">£1.30</td><td><span class="kw-status push">Ranks page 1–2, no ads: push to top</span></td></tr><tr><td>toothpaste whitening</td><td>Core</td><td class="num">29,758</td><td class="num">124</td><td class="num">–</td><td class="num">£0.81</td><td><span class="kw-status missing">Not visible</span></td></tr><tr><td>mouth wash</td><td>Category</td><td class="num">24,719</td><td class="num">27</td><td class="num">–</td><td class="num">–</td><td><span class="kw-status push">Ranks page 1–2, no ads: push to top</span></td></tr><tr><td>gc tooth mousse</td><td>Core</td><td class="num">2,714</td><td class="num">51</td><td class="num">–</td><td class="num">£0.21</td><td><span class="kw-status push">Ranks page 1–2, no ads: push to top</span></td></tr><tr><td>spray</td><td>Core</td><td class="num">4,433</td><td class="num">142</td><td class="num">–</td><td class="num">£0.22</td><td><span class="kw-status missing">Not visible</span></td></tr><tr><td>tooth paste</td><td>Core</td><td class="num">11,507</td><td class="num">80</td><td class="num">–</td><td class="num">£0.66</td><td><span class="kw-status missing">Not visible</span></td></tr><tr><td>toothpastes</td><td>Core</td><td class="num">4,893</td><td class="num">45</td><td class="num">–</td><td class="num">–</td><td><span class="kw-status push">Ranks page 1–2, no ads: push to top</span></td></tr><tr><td>breath</td><td>Core</td><td class="num">2,050</td><td class="num">3</td><td class="num">–</td><td class="num">£0.23</td><td><span class="kw-status organic_top_unprotected">Top organically, no ad cover</span></td></tr><tr><td>travel mouthwash</td><td>Core</td><td class="num">4,362</td><td class="num">12</td><td class="num">–</td><td class="num">–</td><td><span class="kw-status push">Ranks page 1–2, no ads: push to top</span></td></tr><tr><td>kids mouthwash</td><td>Core</td><td class="num">4,176</td><td class="num">58</td><td class="num">–</td><td class="num">–</td><td><span class="kw-status push">Ranks page 1–2, no ads: push to top</span></td></tr><tr><td>fluoride toothpaste</td><td>Core</td><td class="num">6,833</td><td class="num">63</td><td class="num">–</td><td class="num">–</td><td><span class="kw-status missing">Not visible</span></td></tr><tr><td>curaprox toothpaste</td><td>Core</td><td class="num">3,985</td><td class="num">23</td><td class="num">–</td><td class="num">–</td><td><span class="kw-status push">Ranks page 1–2, no ads: push to top</span></td></tr><tr><td>mouth ulcer treatment</td><td>Category</td><td class="num">9,214</td><td class="num">130</td><td class="num">–</td><td class="num">–</td><td><span class="kw-status missing">Not visible</span></td></tr><tr><td>mouthwash for gum disease</td><td>Long-tail</td><td class="num">7,255</td><td class="num">41</td><td class="num">–</td><td class="num">–</td><td><span class="kw-status push">Ranks page 1–2, no ads: push to top</span></td></tr><tr><td>fresh breath</td><td>Core</td><td class="num">1,380</td><td class="num">2</td><td class="num">–</td><td class="num">£0.17</td><td><span class="kw-status organic_top_unprotected">Top organically, no ad cover</span></td></tr><tr><td>oralieve</td><td>Category</td><td class="num">1,675</td><td class="num">32</td><td class="num">–</td><td class="num">£0.34</td><td><span class="kw-status push">Ranks page 1–2, no ads: push to top</span></td></tr><tr><td>bad breath treatment for adults</td><td>Long-tail</td><td class="num">6,721</td><td class="num">9</td><td class="num">–</td><td class="num">–</td><td><span class="kw-status push">Ranks page 1–2, no ads: push to top</span></td></tr></tbody></table></div>
  </section>

  <section>
    <header><span class="eyebrow">Competitors</span><h2>Who is taking the clicks</h2></header>
    <div class="two">
      <div><h3>Share of voice across category searches</h3><div class="hbars"><div class="hbar"><span class="hbar-label">Colgate</span><span class="hbar-track"><span class="hbar-fill" style="width:100.0%" title="Colgate: 18%"></span></span><span class="hbar-value">18%</span></div><div class="hbar"><span class="hbar-label">Marvis</span><span class="hbar-track"><span class="hbar-fill" style="width:68.5%" title="Marvis: 12%"></span></span><span class="hbar-value">12%</span></div><div class="hbar"><span class="hbar-label">Corsodyl</span><span class="hbar-track"><span class="hbar-fill" style="width:61.8%" title="Corsodyl: 11%"></span></span><span class="hbar-value">11%</span></div><div class="hbar"><span class="hbar-label">Oral-B</span><span class="hbar-track"><span class="hbar-fill" style="width:57.3%" title="Oral-B: 10%"></span></span><span class="hbar-value">10%</span></div><div class="hbar"><span class="hbar-label">Euthymol</span><span class="hbar-track"><span class="hbar-fill" style="width:48.9%" title="Euthymol: 9%"></span></span><span class="hbar-value">9%</span></div><div class="hbar"><span class="hbar-label">Listerine</span><span class="hbar-track"><span class="hbar-fill" style="width:42.1%" title="Listerine: 8%"></span></span><span class="hbar-value">8%</span></div><div class="hbar"><span class="hbar-label">CB12</span><span class="hbar-track"><span class="hbar-fill" style="width:34.8%" title="CB12: 6%"></span></span><span class="hbar-value">6%</span></div><div class="hbar"><span class="hbar-label">HISMILE</span><span class="hbar-track"><span class="hbar-fill" style="width:32.6%" title="HISMILE: 6%"></span></span><span class="hbar-value">6%</span></div></div></div>
      <div><h3>Ads on their brand name</h3><ul class="attackers"><li><b>CB12 Mouthwash</b> sponsored at position 4 on “ultradex”<small>CB12 Mouthwash Mint Alcohol Free for 12H Bad Breath Treatment 1 Litre | Chlorhexidine mout</small></li><li><b>CB12 Mouthwash</b> sponsored at position 50 on “ultradex”<small>CB12 Mouthwash Mint Alcohol Free for 12H Bad Breath Treatment 1 Litre | Chlorhexidine mout</small></li><li><b>CB12 Mouthwash</b> sponsored at position 15 on “ultradex mouthwash”<small>CB12 Mouthwash Mint Alcohol Free for 12H Bad Breath Treatment 1 Litre | Chlorhexidine mout</small></li><li><b>CB12 Whitening</b> sponsored at position 50 on “ultradex mouthwash”<small>CB12 Whitening Mouthwash Alcohol Free for 16H Bad Breath Treatment 250ml | Whitening chlor</small></li></ul><p>They had no sponsored placement of their own on those searches.</p></div>
    </div>
  </section>

  <section>
    <header><span class="eyebrow">Amazon Marketing Cloud</span><h2>Path to purchase and repeat buying</h2></header>
    <p>Repeat-purchase signals: high (Subscribe &amp; Save on 62% of ASINs, multipacks 38%, consumable category).</p><div class="two"><div><h3>What we expect AMC to show</h3><ul><li>Most best-sellers offer Subscribe &amp; Save in a repeat-purchase category, so repeat buyers are likely a large share of rinse and spray revenue.</li><li>With CB12 advertising on the brand name, some existing UltraDEX buyers are probably being tempted to switch at the point of reordering.</li></ul></div><div><h3>Questions we would answer in week one</h3><ol><li>How many rinse buyers reorder, and after how many days?</li><li>Do spray buyers go on to buy the rinse or toothpaste?</li><li>How many shoppers who search &#x27;ultradex&#x27; end up buying CB12?</li></ol></div></div>
  </section>

  <section>
    <header><span class="eyebrow">Method</span><h2>How this was put together</h2></header>
    <div class="method"><p>Built from public marketplace data (Keepa, Jungle Scout, DataForSEO, Amazon catalogue and bid recommendations) on 2026-10-21. We have not seen this brand's Seller Central or advertising account, so spend and budget figures are estimates.</p><p>Budget model: search volume × 12% of searches producing an ad click × target sponsored share of voice by tier × CPC benchmark, plus 15% for remarketing.</p><details><summary>Data gaps in this run</summary><ul><li>images: can&#x27;t reach m.media-amazon.com (&lt;urlopen error Tunnel connection failed: 403 Forbidden&gt;); add it to Allowed domains</li><li>spapi.items: SP-API not configured</li><li>ads.bids: Ads API not configured; using Jungle Scout PPC bids</li></ul></details></div>
  </section>

  <footer>Smart PPC · smartppc.ai</footer>
</main>
```

### `audits/ultradex-uk-2026-10-21/UltraDEX-Amazon-Audit.pdf`

Binary file (636,965 bytes): the A4 print of `audit.html` made by `analyse/pdf.py`. Not reproducible as text; regenerate with `python -m analyse.pdf <run folder>`.
