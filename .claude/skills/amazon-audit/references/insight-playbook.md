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
