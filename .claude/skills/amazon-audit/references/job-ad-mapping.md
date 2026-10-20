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
