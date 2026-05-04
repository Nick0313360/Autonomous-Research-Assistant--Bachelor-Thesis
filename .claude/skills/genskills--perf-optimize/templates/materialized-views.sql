-- Pre-compute expensive aggregations
CREATE MATERIALIZED VIEW monthly_revenue AS
SELECT date_trunc('month', created_at) AS month, SUM(amount) AS total
FROM orders GROUP BY 1;

-- Refresh strategy:
REFRESH MATERIALIZED VIEW CONCURRENTLY monthly_revenue;
-- CONCURRENTLY allows reads during refresh (requires a unique index on the view)
-- Schedule refresh with pg_cron or application-level cron
