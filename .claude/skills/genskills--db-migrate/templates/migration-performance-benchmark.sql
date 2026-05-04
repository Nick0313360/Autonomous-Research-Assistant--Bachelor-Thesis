-- Check table size
SELECT
  pg_size_pretty(pg_total_relation_size('users')) AS total_size,
  pg_size_pretty(pg_relation_size('users')) AS table_size,
  pg_size_pretty(pg_indexes_size('users')) AS index_size,
  (SELECT reltuples::BIGINT FROM pg_class WHERE relname = 'users') AS estimated_rows;

-- Time the migration on a clone
\timing on
-- Run migration SQL here
