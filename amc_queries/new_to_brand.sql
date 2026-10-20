-- Share of ad-attributed purchases that were new-to-brand (no brand purchase in prior 12 months).
-- Output columns: purchases, ntb_purchases
SELECT
  SUM(purchases) AS purchases,
  SUM(new_to_brand_purchases) AS ntb_purchases
FROM amazon_attributed_events_by_conversion_time
