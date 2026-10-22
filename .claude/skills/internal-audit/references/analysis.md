# Reading internal_audit.json

Field names refer to `internal_audit.json`. Thresholds are the ones used for W7; adjust with care.

## 1. Sales, conversion, TACoS (`business`, `periods`)
- Per period: sales, units/day, conversion (units ÷ sessions), Sponsored Products spend and units.
- Ad spend ÷ sales: add Sponsored Brands spend from `campaigns` (campaign level only; pro-rate and label it
  "estimate" when the dates don't line up).
- Organic units ≈ Business Report units − SP ad units − SB orders. Organic conversion ≈ organic units ÷
  (sessions − ad clicks). Ad cost per unit vs price is the headline when ads cost more than the product.
- Benchmarks: the brand's own sets in the target category (rows in the full Business Report; check categories
  with Keepa) and the same product in another marketplace.

## 2. Category
Keepa category path vs the other marketplace and rivals. Impression share on the brand's own search (from
Search Query Performance) is the practical ceiling for one listing. Near-ceiling share on category searches
means the category isn't hiding it there.

## 3. Where to push spend (`sqp.rows`, `query_spend`, `targeting.in_account`)
Last 3 weeks by default (`--sqp-weeks`). Ratio = purchase share ÷ click share.
- **push** ≥ 1.05×, **hold** 0.85–1.05×, **cut** < 0.85×.
- **defend**: own-brand searches. **test**: rival-brand searches. **cut** also: off-target words and
  searches containing "amazon" (shoppers after Amazon's own product).
- Rows need ≥3 product purchases unless they're big rival or off-target searches.
- Add `query_spend` (spend, orders, cost per order) and flag cost per order above `cpo_alert` (default $40) or
  ≥$25 spent with no orders. `targeting.in_account` says whether the search is an actual keyword (match types)
  or only reached through phrase/auto/product targeting.

## 4. Campaigns (`campaigns`, `advertised.by_campaign`)
Budget, bid strategy ("down only" never raises bids), top-of-search adjustment, spend, orders, cost per order,
ACOS. Verdicts: BEST / EXPAND (cheapest per order), FIX, TIGHTEN (big budget, mid cost), CUT (cost per order
above price).

## 5. Where the ad money has gone (`search_terms.buckets`, `placement`, `rank_weekly`, `advertised.weekly`)
- Buckets: generic, category, audience, rival product pages, rival brand searches, Amazon's own, off-target,
  own brand. Give each a verdict in `bucket_verdicts`.
- Placement: share of spend and cost per order by placement; top of search by campaign. Recommend placement
  adjustments only where that placement is cheaper per order.
- Ranking: weekly SP spend and orders against Keepa's weekly median sales rank. Say whether rank kept improving
  as spend rose, note price changes in `weekly_price`, and say when the two can't be separated.

## 6. Actions and targets
5–8 actions, each: what to do and how much (title), detail, and one line of evidence (`why`). Targets: ad spend
÷ sales, ad cost per unit, conversion, organic units per day, cost per order at the worst placement.
