# Amazon Prospect Audit

An outside-in audit of a prospect's Amazon business, used for consultant outreach. Paste in a brand store URL, a
product URL, an ASIN or a brand name, and optionally a job advert. You get back:

- **`email.md`**: a short outreach email with up to 5 points, written in the prospect's own words
- **`audit.html`**: a one-page visual audit covering the catalogue, listing content, keyword map and budget,
  competitors, and AMC hypotheses
- **`evidence.md`**: the data behind every claim

The Python collectors pull and compute the numbers. The Claude skill in `.claude/skills/amazon-audit/` decides what
matters and writes the output.

## Setup
```bash
cp .env.example .env   # fill in what you have; Keepa is the only hard requirement
python -m pytest       # offline tests, no keys needed
```
Python 3.11+ is required. There are no third-party dependencies at runtime; `pytest` is only needed for the tests.

## Use
In Claude Code, from this repo:
> audit https://www.amazon.co.uk/stores/Acme/page/… (here's their job ad: …)

Or run the steps yourself:
```bash
python run_audit.py "<url | ASIN | brand>" --job-ad job.txt   # → runs/<slug>/dataset.json
# write runs/<slug>/findings.json (the skill does this)
python -m analyse.render runs/<slug>                          # → audit.html, evidence.md
```

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
