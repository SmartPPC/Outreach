---
name: internal-audit
description: Internal Amazon account audit from a client's own data. Turns Seller Central and Amazon Ads exports (Business Reports, Brand Analytics Search Query Performance, Sponsored Products advertised product / search term / targeting / placement reports, campaign list) into a client-branded PDF covering conversion, category, where to push spend, where the ad money has gone, placement, ranking impact and actions. Use when the user is in a client's Seller Central or Ads console, asks which reports to pull, uploads those exports, or asks for a deep dive, ads review, TACoS or "is the spend working" analysis on a product or brand. For outside-in prospect audits and outreach emails, use the outreach skill instead.
---

# Internal account audit

For accounts we can see inside: the client (or the user, logged into the client's accounts) exports reports, and we
turn them into a short, factual, client-branded PDF.

Outputs, in `runs/<brand>-<asin>-<mp>-internal-<YYYY-MM-DD>/`:
- `internal_audit.json`: every number, built by `analyse/internal_audit.py`
- `internal_findings.json`: wording, colours, verdicts and actions, written by you
- `internal-report.html` and `<Brand>-<ASIN>-<MP>-Account-Review.pdf`, built by `analyse/internal_report.py`

The scripts do the arithmetic and are the source of truth. You decide what matters and write it.

## Ground rules
- **Client-facing.** Use the client's brand name and colours. No Smart PPC branding, names or links anywhere in
  the report. (The outreach skill is where the Smart PPC format lives.)
- **Large print.** Nothing below 14pt; the template enforces it. Expect 6–8 portrait A4 pages.
- **Bare facts.** Short statements with numbers. No filler, no "it's worth noting", no rhetorical lead-ins, no
  sign-off phrases. Bold only the key figure in a line. A reader should be able to act on each line.
- **Every number from the data.** If it isn't in `internal_audit.json`, a report the user sent, or a figure the
  user gave you (say so in the report, e.g. "UK conversion ~5%, W7's figure"), leave it out.
- **Correct yourself in the open.** If a later report contradicts an earlier conclusion, say so plainly to the
  user and fix the report.
- **Single product or brand.** Default to the product the user names. Keep other products out unless asked.

## Steps
1. **Ask for the reports.** Use `references/reports-to-pull.md` and walk the user through it click by click.
   Answer navigation questions from it ("Pending" means wait, the new Seller Central menu has no Reports item,
   and so on). Ask which date each Business Report covers if the user doesn't say.
2. **Build the data.** Uploads land in `/root/.claude/uploads/<session>/`. Run:
   ```bash
   python -m analyse.internal_audit runs/<slug> --uploads <dir> --asin <ASIN> --marketplace us --brand "<Brand>" \
     --brand-terms "<product line names>" --campaign-match "<word in the relevant campaign names>" \
     --rivals "<rival brand words>" --category-words "<in-category words>" --off-target "<other-product words>" \
     --period "<label>|<start>|<end>|<business report file name>"   # one per Business Report
   ```
   Check the printed totals against the console before writing. `--campaign-match` keeps the analysis to the
   product's own campaigns (e.g. `ADVENT`). Keepa rank history comes from the cache when the outreach audit
   already ran on the ASIN; otherwise it costs ~2 tokens.
3. **Read it.** Work through `references/analysis.md`: conversion, category, Search Query Performance groups,
   spend per search, spend by search type, keyword-in-account check, placement, ranking.
4. **Write `internal_findings.json`.** Copy `templates/internal_findings.example.json` (the W7 report) and
   replace every field. Set `brand_colours` to the client's colours. Name each relevant campaign in
   `campaign_labels`. Use `group_overrides` / `exclude_queries` when a search lands in the wrong group.
5. **Render:** `python -m analyse.internal_report runs/<slug>`. Look at every page (render PNGs with `pdftoppm`)
   and fix stranded headings or near-empty pages before sending.
6. **Deliver.** Send the PDF with the file tool (`display: attach` when the user wants to download it). Copy the
   run folder's PDF, HTML and JSON into `audits/<slug>/`, commit and push. Downloads can't be written to the
   user's computer from a cloud session; the file card is how they save it.

## Lessons from the W7 Beauty Blast audit (Oct 2026)
- **Low top-of-search share ≠ low top-of-search spend.** W7 had 2–7% top-of-search share on its main keywords,
  yet 52% of spend landed at the top of search, its most expensive placement ($38/order vs $26 for rest of
  search). Never recommend a top-of-search boost before reading the Placement report.
- **Jungle Scout's sponsored "–" was wrong.** Ads ran on all 14 "no ad" searches through phrase, auto and
  product targeting. Use the Search term and Targeting reports to say what's really bid on.
- **Conversion needs a benchmark.** The brand's own sets in the right category and the same product in another
  marketplace (W7 UK ~5% vs US 2.5%) say more than a generic "8–15% is healthy". Gift sets convert far below
  single products.
- **Category:** Search Query Performance impression share on the brand's own search sets the ceiling (~3–4%).
  If category searches already sit near it, the category isn't hiding the product there; the case for moving
  it is broad-search relevance, the Best Seller badge, and the other marketplace's conversion.
- **TACoS and organic:** organic units = total units (Business Report) − Sponsored Products units − Sponsored
  Brands orders. Ads lifting rank can be good spend even at a poor ACOS; check whether rank still improves as
  spend rises (W7 plateaued at ~6,500 while spend ran at $2k/day).
- **Spend per search beats spend per campaign.** One amber search ("beauty advent calendar", $4,100 at $49 per
  order) was the second-biggest drain and invisible at campaign level.
- **Rival-brand searches:** check the purchase ÷ click ratio before recommending them. W7 converted at half the
  market rate on Sephora and e.l.f. searches; rival product-page targeting was the cheap route.
- **Total spend for a date range:** Sponsored Products from the daily advertised product report is exact;
  Sponsored Brands only comes at campaign level unless the user runs it Daily, so label any split as an estimate.
