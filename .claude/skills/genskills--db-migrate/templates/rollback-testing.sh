# Apply
npx knex migrate:latest
# Verify schema matches expected state
# Rollback
npx knex migrate:rollback
# Verify schema returns to previous state
# Re-apply to confirm idempotency
npx knex migrate:latest
