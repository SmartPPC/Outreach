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
