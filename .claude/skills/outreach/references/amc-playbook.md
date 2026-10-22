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
