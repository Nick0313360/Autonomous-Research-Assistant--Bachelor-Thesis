-- PostgreSQL: check for recently created objects not in migration files
SELECT
  c.relname AS object_name,
  CASE c.relkind
    WHEN 'r' THEN 'table'
    WHEN 'i' THEN 'index'
    WHEN 'v' THEN 'view'
    WHEN 'm' THEN 'materialized view'
  END AS object_type
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'i', 'v', 'm')
ORDER BY c.relname;
