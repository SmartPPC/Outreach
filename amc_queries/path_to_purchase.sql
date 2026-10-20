-- Ad touches before each converting user's FIRST purchase, bucketed.
-- Output columns: touch_bucket, users
-- Validate column names in the AMC schema explorer for your instance before first use.
WITH touches AS (
  SELECT user_id, event_dt FROM sponsored_ads_traffic WHERE user_id IS NOT NULL
  UNION ALL
  SELECT user_id, impression_dt AS event_dt FROM dsp_impressions WHERE user_id IS NOT NULL
),
first_purchase AS (
  SELECT user_id, MIN(event_dt) AS first_purchase_dt
  FROM conversions
  WHERE event_subtype = 'order' AND user_id IS NOT NULL
  GROUP BY user_id
),
per_user AS (
  SELECT p.user_id, COUNT(t.event_dt) AS touches
  FROM first_purchase p
  LEFT JOIN touches t ON t.user_id = p.user_id AND t.event_dt <= p.first_purchase_dt
  GROUP BY p.user_id
)
SELECT
  CASE WHEN touches >= 5 THEN '5+' ELSE CAST(touches AS VARCHAR) END AS touch_bucket,
  COUNT(user_id) AS users
FROM per_user
GROUP BY 1
