-- Purchase rate by combination of sponsored ad types a shopper was exposed to.
-- Output columns: sp, sb, sd, exposed_users, purchasers
WITH exposure AS (
  SELECT user_id,
         MAX(CASE WHEN ad_product_type = 'sponsored_products' THEN 1 ELSE 0 END) AS sp,
         MAX(CASE WHEN ad_product_type = 'sponsored_brands' THEN 1 ELSE 0 END) AS sb,
         MAX(CASE WHEN ad_product_type = 'sponsored_display' THEN 1 ELSE 0 END) AS sd
  FROM sponsored_ads_traffic
  WHERE user_id IS NOT NULL
  GROUP BY user_id
),
buyers AS (
  SELECT user_id, 1 AS purchased
  FROM conversions
  WHERE event_subtype = 'order' AND user_id IS NOT NULL
  GROUP BY user_id
)
SELECT e.sp, e.sb, e.sd,
       COUNT(e.user_id) AS exposed_users,
       SUM(COALESCE(b.purchased, 0)) AS purchasers
FROM exposure e
LEFT JOIN buyers b ON b.user_id = e.user_id
GROUP BY e.sp, e.sb, e.sd
