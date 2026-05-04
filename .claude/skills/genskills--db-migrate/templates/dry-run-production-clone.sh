# PostgreSQL: create a test database from production dump
pg_dump --schema-only production_db > schema.sql
pg_dump --data-only --table=critical_config_table production_db >> schema.sql
createdb migration_test
psql migration_test < schema.sql

# Or use a recent snapshot/replica
# Then run migration against the clone
npx prisma migrate deploy  # or equivalent
