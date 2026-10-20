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
