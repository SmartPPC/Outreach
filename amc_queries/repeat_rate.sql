-- Repeat-purchase behaviour: share of buyers who order again, and how fast.
-- Use a long time window (>= 6 months) so repurchase cycles fit inside it.
-- Output columns: buyers, repeat_buyers, repeat_30d, repeat_60d, repeat_90d, avg_days_to_repeat
WITH orders AS (
  SELECT user_id, event_dt
  FROM conversions
  WHERE event_subtype = 'order' AND user_id IS NOT NULL
),
ranked AS (
  SELECT user_id, event_dt, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY event_dt) AS n
  FROM orders
),
firsts AS (
  SELECT user_id,
         MAX(CASE WHEN n = 1 THEN event_dt END) AS d1,
         MAX(CASE WHEN n = 2 THEN event_dt END) AS d2
  FROM ranked
  GROUP BY user_id
)
SELECT
  COUNT(user_id) AS buyers,
  SUM(CASE WHEN d2 IS NOT NULL THEN 1 ELSE 0 END) AS repeat_buyers,
  SUM(CASE WHEN d2 IS NOT NULL AND DATE_DIFF('day', d1, d2) <= 30 THEN 1 ELSE 0 END) AS repeat_30d,
  SUM(CASE WHEN d2 IS NOT NULL AND DATE_DIFF('day', d1, d2) <= 60 THEN 1 ELSE 0 END) AS repeat_60d,
  SUM(CASE WHEN d2 IS NOT NULL AND DATE_DIFF('day', d1, d2) <= 90 THEN 1 ELSE 0 END) AS repeat_90d,
  AVG(CASE WHEN d2 IS NOT NULL THEN DATE_DIFF('day', d1, d2) END) AS avg_days_to_repeat
FROM firsts
