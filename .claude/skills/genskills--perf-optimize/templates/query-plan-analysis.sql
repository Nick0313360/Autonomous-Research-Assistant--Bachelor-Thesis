-- PostgreSQL: full execution statistics
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) SELECT ...;

-- Look for:
--   Seq Scan on large tables → add an index
--   Nested Loop with high row estimates → consider hash join (check indexes)
--   Sort with high cost → add index matching the ORDER BY
--   Buffers: shared hit vs read → low hit ratio means data not cached
--   Actual rows vs planned rows → large discrepancy means stale statistics (run ANALYZE)

-- MySQL
EXPLAIN ANALYZE SELECT ...;
-- Or: EXPLAIN FORMAT=TREE SELECT ...;
