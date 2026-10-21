---
name: amazon-audit
description: Audit a prospect's Amazon business from the outside and draft a consultant outreach email with up to 5 improvement points plus a one-page visual audit. Use when the user pastes an Amazon brand store URL, seller URL, product URL, ASIN or brand name and wants a prospect audit, outreach email, or "what would we fix" summary, optionally alongside a job advert.
---

# Amazon prospect audit

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
