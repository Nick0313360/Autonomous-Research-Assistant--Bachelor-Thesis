-- List columns not in your expected schema
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name NOT IN ('_prisma_migrations', 'schema_migrations')
ORDER BY table_name, ordinal_position;

-- Compare against a known-good schema dump
pg_dump --schema-only production_db > actual_schema.sql
pg_dump --schema-only reference_db > expected_schema.sql
diff actual_schema.sql expected_schema.sql
