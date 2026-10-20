# Insight playbook: from finding to phrasing

| Dataset signal | Recommendation | Email phrasing (adapt) |
|---|---|---|
| `competitors.brand_term_attackers` non-empty, `prospect_sponsored_on_own_brand` false | Launch brand defence SP + SB | "<Rival> is buying the top ad slot when shoppers search '<brand>', and you're not there to block it." |
| Several `push` focus keywords | Top-of-search SP exact on page-1 terms | "You already rank on page one for '<term>' (<vol> searches/mo) but sit below the fold, so a small exact-match campaign moves you to the top." |
| `ads_observed.sponsored_coverage` < 0.3 | Expand coverage of top terms | "We only saw you advertising on <n> of your top 30 keywords." |
| `content.summary.share_no_video` ≥ 0.5 | Video on hero ASINs + SB Video | "<x> of your top <n> listings have no video, which also rules out Sponsored Brands Video." |
| `share_no_aplus` ≥ 0.3 | A+ rollout | "<x> best-sellers are missing A+ content, so that's free conversion lift." |
| `share_under_7_images` ≥ 0.5 | Image stack (infographics, lifestyle, scale) | "Most listings use <n> of the 7+ image slots." |
| `variation_consolidation` non-empty | Merge into variation families | "<n> separate listings look like one product in different sizes. Combining them pools reviews and rank." |
| Hero ASIN rating < 4.0 | Fix before scaling | "Your top seller is at <r>★. We'd fix the review drivers before pushing more traffic to it." |
| `catalogue.launches_last_12m` high + weak content on new ASINs | Launch playbook | "You've launched <n> ASINs in the last year, but the newest ones have the thinnest listings." |
| `catalogue.revenue_yoy_pct_last_3m` < 0 or BSR worsening | Recover share | "Rank on your top sellers has slipped ~<x>% year on year while <rival> has grown." |
| `top3_revenue_share` > 0.6 | De-risk concentration | "Three ASINs drive roughly <x>% of sales, so growing the rest of the range lowers the risk." |
| `competitors.sov_change_vs_last_run` shows a rival rising | Respond to a specific rival | "<Rival> has taken ~<x> points of share on your core terms since <date>." |
| `positioning_page1` price well above competitors with a lower rating | Value story in content | "You're priced ~<x>% above the page-one median with a lower rating, so the listing needs to justify the premium." |
| `repeat_signals.likelihood` high, no SD visible | Retention / remarketing | "Your category is built on repeat orders. AMC would show how many of your buyers come back, and we'd build audiences around that." |

Tone: specific, generous, confident. Show we did the homework. Each point should feel like a free
insight they could act on, while making it clear that doing it well takes an expert.
