---
name: amazon-audit
description: Audit a prospect's Amazon business from the outside and draft a consultant outreach email with up to 5 improvement points plus a one-page visual audit. Use when the user pastes an Amazon brand store URL, seller URL, product URL, ASIN or brand name and wants a prospect audit, outreach email, or "what would we fix" summary, optionally alongside a job advert.
---

# Amazon prospect audit

Turns a brand, store URL or ASIN (plus an optional job advert) into:
- `runs/<slug>/email.md`: a short outreach email with up to 5 points
- `runs/<slug>/audit.html`: a one-page visual audit, published as a private artifact link
- `runs/<slug>/evidence.md`: the data behind every claim, for the follow-up call

The Python collectors handle data and arithmetic, and their numbers are the source of truth. Your job is judgement and writing: decide what matters, connect it to what the prospect is asking for, and say it the way a senior consultant would.

## Ground rules
- **Outside-in only.** We have not seen their Seller Central or ad account. Never write as if we have. Spend, revenue and budget figures are estimates and must be labelled that way: "we estimate", "roughly", "looks like".
- **Every point needs evidence from `dataset.json`.** If a number isn't in the dataset, don't use it. If a section is empty because a provider was skipped, leave it out. Don't fill gaps with guesses.
- **AMC numbers are category benchmarks from other accounts, never this prospect's.** Phrase them as hypotheses ("in your category, typically…"). If the benchmark says `low_sample: true` or isn't available, describe what AMC would show without quoting figures.
- **Never name our clients** or reveal any single client's numbers.

## Steps

### 1. Gather inputs
Get the prospect identifier from the user. If they gave a job advert:
- **Pasted text:** save it to a file.
- **URL:** fetch the page and save the advert text to a file.

Pass that file with `--job-ad`. If the marketplace isn't obvious from the URL, ask whether it's UK or US.

### 2. Collect
```bash
python run_audit.py "<input>" [--marketplace uk|us] [--job-ad /path/job.txt]
```
This prints the run directory. Check `collect_log.json` in it:
- If Keepa was skipped there is no ASIN map. Stop and tell the user which key is missing.
- Other skipped providers just make the audit thinner. Mention them in your reply.

Cost controls: `--max-asins` (default 150), `--top-n` (default 10), and the `APA_BUDGET_*` environment variables. Reruns on the same day hit the cache and cost nothing.

If a connected MCP server covers a provider whose API key is missing (Jungle Scout, Amazon Ads or Keepa), you may use it to fill that gap by hand. Record what you pulled in `evidence.md`.

### 3. Analyse
Read `dataset.json`, then `job_ad.txt` if present, and these references:
- `references/scoring-rubric.md`: what the content checks mean and when they matter
- `references/ad-strategy-framework.md`: keyword tiers, visibility logic, budget
- `references/amc-playbook.md`: AMC hypotheses and week-one questions
- `references/insight-playbook.md`: finding → recommendation → phrasing
- `references/job-ad-mapping.md`: only when there's a job ad

Spot-check the two claims you'll lean on hardest by opening the live listing or search page. For example, open the product page and confirm there's no video before you say so.

### 4. Pick up to 5 points
List every candidate finding, then score each one from 1 to 3 on three things:
- **Impact:** revenue at stake, e.g. a top-seller listing or a high-volume keyword.
- **Confidence:** directly observed beats estimated.
- **Fixable by us:** PPC, listings and AMC are our core. Supply chain or pricing is not.

Multiply the three scores. Matching what the job ad asks for adds one extra point to impact.

Keep the top 5 and cover at least three different areas (content, ads, catalogue, competitors, AMC). Fewer, stronger points beat five weak ones.

### 5. Write `findings.json`
```json
{
  "headline": "One sentence: the single biggest opportunity, specific to them.",
  "points": [
    {
      "category": "advertising | content | catalogue | competitors | amc",
      "title": "Short imperative, e.g. 'Defend your brand name from Brand X'",
      "detail": "2-3 sentences: what we saw, why it costs them, what we'd do.",
      "evidence": ["Specific data points with numbers and sources from dataset.json"],
      "job_ad_quote": "Exact phrase from the job ad this answers, or null"
    }
  ],
  "catalogue_note": "1-2 sentences reading the growth charts.",
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
Publish `runs/<slug>/audit.html` as a private Artifact if the Artifact tool is available:
- icon `chart`
- description "Outside-in Amazon audit for <brand>"

Otherwise give the user the file path.

### 7. Write `email.md`
Follow `templates/email.md`. Keep it under 150 words, use the prospect's own language from the job ad, and pick 3–5 bullets, each with one number. End with a soft call to action and a link placeholder for the audit page.

### 8. Reply to the user
Include:
- the email text
- the audit link
- one line listing any data gaps, e.g. "no Jungle Scout key, so keyword and sales sections are thin"
