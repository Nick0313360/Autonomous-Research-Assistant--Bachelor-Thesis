---
name: genskills:db-migrate
description: >
  Generate and manage database migrations - Prisma, Drizzle, Knex, Django,
  Alembic. Diff schemas, validate migration safety. Triggers on: "create migration",
  "schema change", "database migration", "db migrate", "add column", "alter table".
user-invocable: true
argument-hint: "[description of schema change]"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(npx prisma *), Bash(npx drizzle-kit *), Bash(npx knex *), Bash(python *), Bash(alembic *), Bash(npm run *), Bash(npx typeorm *), Bash(ruby *), Bash(rails *), Bash(mongosh *), Bash(redis-cli *), Bash(pg_dump *), Bash(mysqldump *), Bash(sqlite3 *), Bash(psql *), Bash(mysql *), Bash(gh-ost *), Bash(pt-online-schema-change *)"
genskills-version: "1.4.2"
genskills-category: "development"
genskills-depends: []
---

# Database Migration

Generate, validate, and safely execute database migrations across all major ORMs, databases, and deployment topologies.

---

## Process

### Step 0: Load Project Context

- Check for `CLAUDE.md` at the project root - follow any database/migration conventions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Check for existing migrations to understand naming conventions and patterns
- Identify the current deployment model (single server, replicated, sharded, multi-region) as this affects migration strategy
- Check for a `docker-compose.yml` or infrastructure config to understand the database topology

### Step 1: Detect ORM / Migration Tool

Check for:
- `prisma/schema.prisma` → Prisma
- `drizzle.config.*` / `drizzle/` → Drizzle
- `knexfile.*` → Knex
- `alembic.ini` / `alembic/` → Alembic
- `*/migrations/` with Django patterns → Django
- `db/migrate/` → Rails (ActiveRecord)
- `typeorm` in dependencies → TypeORM
- `sequelize` in dependencies → Sequelize
- `mongoose` in dependencies → Mongoose (MongoDB)
- `migrations/` with raw `.sql` files → plain SQL migrations (e.g., golang-migrate, Flyway, Liquibase)
- Raw SQL migrations directory

Detect the target database engine as well:
- `DATABASE_URL` or connection config containing `postgresql` / `postgres` → PostgreSQL
- `DATABASE_URL` containing `mysql` → MySQL / MariaDB
- `DATABASE_URL` containing `sqlite` or `.db` file references → SQLite
- `MONGODB_URI` or `mongoose.connect` → MongoDB
- `REDIS_URL` or `ioredis` / `redis` in dependencies → Redis

### Step 2: Understand the Change

Parse `$ARGUMENTS` for the desired schema change:
- Adding a table/model
- Adding/removing/modifying columns
- Adding indexes or constraints
- Changing relationships (foreign keys, many-to-many)
- Renaming tables/columns
- Data backfill or transformation
- Partitioning or sharding changes
- Row-level security policy changes
- Seed data additions or updates

If unclear, ask the user to describe the schema change in plain language.

### Step 3: Generate Migration

#### Prisma

1. Edit `schema.prisma` with the schema change
2. Run `npx prisma migrate dev --name <descriptive-name> --create-only`
3. Review the generated SQL migration file
4. Check `npx prisma validate` for schema errors

**Prisma-specific considerations:**
- **`prisma db push` vs `prisma migrate dev`**: `db push` is for prototyping only - it does not create migration files and cannot be used in production. Always use `migrate dev` for anything beyond local throwaway work.
- **Shadow database**: Prisma uses a shadow database to detect drift and generate migrations. Ensure the dev user has `CREATE DATABASE` privileges, or configure `shadowDatabaseUrl` in `schema.prisma`.
- **Multi-schema support** (PostgreSQL): Use the `schemas` preview feature and `@@schema("schema_name")` attribute. Ensure all referenced schemas exist before migrating.
- **Baseline migrations**: When adopting Prisma on an existing database, run `npx prisma migrate resolve --applied <migration-name>` to mark the baseline migration as already applied.
- **Custom migration SQL**: After `--create-only`, you can edit the generated SQL before applying. This is the right place to add `CONCURRENTLY` index creation, data backfills, or database-specific syntax Prisma cannot generate.

#### Drizzle

1. Edit the schema file (e.g., `drizzle/schema.ts`)
2. Run `npx drizzle-kit generate`
3. Review generated migration
4. Drizzle generates raw SQL - inspect for safety before applying with `npx drizzle-kit migrate`

#### Knex

1. Run `npx knex migrate:make <name>`
2. Edit the generated migration file with `up` / `down` functions
3. Ensure the `down` migration correctly reverses the `up`
4. For large tables, use `knex.raw()` to issue database-specific DDL (e.g., `CREATE INDEX CONCURRENTLY`)

#### Alembic

1. Edit SQLAlchemy models
2. Run `alembic revision --autogenerate -m "<description>"`
3. Review generated migration - autogenerate misses: table renames (detected as drop+create), changes to column names, `Enum` value changes, and custom types
4. Verify both `upgrade()` and `downgrade()` functions

**Alembic-specific considerations:**
- **Branching**: When two developers create migrations from the same head, Alembic detects branching. Resolve with `alembic merge -m "merge heads" <rev1> <rev2>`.
- **Stamping**: To mark a database as being at a specific revision without running migrations: `alembic stamp <revision>`. Useful for baselining.
- **Offline mode**: Generate SQL scripts without a database connection using `alembic upgrade head --sql > migration.sql`. Essential for DBA-reviewed production deployments.
- **Multiple databases**: Use Alembic's multi-database template or configure separate `alembic.ini` environments.

#### TypeORM

1. Edit entity files
2. Run `npx typeorm migration:generate -n <name>`
3. Review generated migration

**TypeORM-specific considerations:**
- **QueryRunner transactions**: Wrap multi-step migrations in `await queryRunner.startTransaction()` / `commitTransaction()` / `rollbackTransaction()` for atomicity (MySQL does not support transactional DDL - each statement commits implicitly).
- **Custom naming strategies**: If the project uses a `NamingStrategy`, ensure generated migrations respect it. Check `ormconfig` or `DataSource` options.
- **`synchronize: true`**: This must NEVER be enabled in production. It auto-applies schema changes without migrations, causing data loss and drift.

#### Django

1. Edit model files
2. Run `python manage.py makemigrations <app_label>`
3. Review migration file in `<app>/migrations/`
4. Validate with `python manage.py migrate --plan`

**Django-specific considerations:**
- **Data migrations**: Create with `python manage.py makemigrations --empty <app_label>`, then add a `RunPython` operation with both forward and reverse functions.
- **Squashing**: When migration count becomes unwieldy: `python manage.py squashmigrations <app_label> <start_migration> <end_migration>`. Replace the squashed set only after all environments have applied the originals.
- **`RunSQL`**: For raw SQL operations, always provide both forward and reverse SQL. Mark non-reversible migrations with `state_operations` if needed.
- **Migration dependencies**: Use `dependencies = [('other_app', '0005_auto')]` to enforce cross-app ordering.

#### Rails (ActiveRecord)

1. Run `rails generate migration <MigrationName>`
2. Edit the generated migration file in `db/migrate/`
3. Use `change` method for reversible operations; use `up` / `down` for irreversible ones
4. For large-table operations, consider `disable_ddl_transaction!` with manual safety

#### Raw SQL Migrations

1. Create a new `.sql` file following the project's naming convention (e.g., `V003__add_user_email.sql`)
2. Write idempotent SQL when possible (see Idempotent Migrations below)
3. Include a corresponding rollback file if the framework supports it

---

### Step 4: Safety Validation

**Before applying, check EVERY generated migration for:**

#### Data Loss Risks

- `DROP COLUMN` / `DROP TABLE` → data is permanently deleted
- Column type changes that lose precision (e.g., `TEXT` → `VARCHAR(100)`, `BIGINT` → `INT`)
- `TRUNCATE` statements
- Removing enum values that are currently referenced by rows
- Dropping constraints that implicitly cascade (e.g., `DROP TABLE ... CASCADE`)

#### Locking Risks (can cause downtime on large tables)

- `ALTER TABLE` on tables with millions of rows
- Adding indexes without `CONCURRENTLY` (PostgreSQL)
- Adding `NOT NULL` constraint requiring full table scan
- Adding a column with a volatile `DEFAULT` on older PostgreSQL (<11) or MySQL (<8.0.12)
- `RENAME TABLE` / `RENAME COLUMN` (acquires exclusive lock on most engines)
- Adding or dropping foreign key constraints

**Table lock duration estimation:**
```
Estimated lock time factors:
- Row count: Query SELECT count(*) or reltuples from pg_class / TABLE_ROWS from information_schema
- < 100K rows: Usually safe for inline ALTER, expect seconds
- 100K–1M rows: Caution - may lock for seconds to minutes depending on operation
- 1M–10M rows: High risk - use online DDL tools or CONCURRENTLY
- > 10M rows: Require online schema change tooling (gh-ost, pt-osc) or zero-downtime patterns
- Index build time: Proportional to table size and index width. CONCURRENTLY takes ~2-3x longer but does not lock.
- Disk space: ALTER TABLE may temporarily require 1x–2x table size for rewrite operations. CREATE INDEX CONCURRENTLY requires space proportional to the index. CHECK before running: SELECT pg_size_pretty(pg_total_relation_size('table_name'));
```

#### Connection Limit Impact

- Long-running DDL can hold locks that cause connection pile-up
- Check `max_connections` and current active connections before large migrations
- For PostgreSQL: `SELECT count(*) FROM pg_stat_activity;`
- For MySQL: `SHOW STATUS LIKE 'Threads_connected';`
- Consider setting a `lock_timeout` to fail fast rather than block: `SET lock_timeout = '5s';` (PostgreSQL)

#### Replication Lag Monitoring

On replicated setups, large migrations can cause replicas to fall behind:
- **PostgreSQL**: Monitor `pg_stat_replication` for `replay_lag`
- **MySQL**: Monitor `Seconds_Behind_Master` or GTID-based lag
- Pause or throttle migration if lag exceeds threshold (e.g., 10 seconds)
- Tools like `gh-ost` have built-in `--max-lag-millis` throttling

#### Nullability Risks

- Adding `NOT NULL` column without `DEFAULT` on table with existing data → migration WILL fail
- Safe pattern: add column as nullable → backfill data → add `NOT NULL` constraint

#### Backwards Compatibility

- Can the currently deployed code still work during and after this migration?
- Column renames break old code - use the expand-contract pattern
- Dropping columns breaks old code that references them - deploy code removal first
- Changing column types may break ORM type mappings or application casts

#### Flag Dangerous Operations and Suggest Safe Alternatives

| Dangerous Operation | Safe Alternative |
|---|---|
| `DROP COLUMN` | Deploy code that stops reading it first, then drop in next release |
| `NOT NULL` without default | Add as nullable → backfill → add constraint |
| Large index creation | `CREATE INDEX CONCURRENTLY` (Postgres) or schedule off-peak |
| Column rename | Add new column → copy data → update code → drop old column |
| Table rename | Create new table → migrate data → update code → drop old table |
| `DROP TABLE` | Rename to `_deprecated_<table>` first, drop after verification period |
| Changing column type | Add new column with new type → backfill with cast → swap in code → drop old |
| Adding foreign key on large table | Create as `NOT VALID` then `VALIDATE CONSTRAINT` separately (PostgreSQL) |

---

### Step 5: Zero-Downtime Migration Patterns

#### Expand-Contract Pattern (Add → Migrate → Remove)

The canonical approach for any schema change that would break running application code:

**Phase 1 - Expand (additive, non-breaking):**
```sql
-- Add new column alongside old one
ALTER TABLE users ADD COLUMN email_address VARCHAR(255);
```
Deploy code that writes to BOTH old and new columns. Old code still works.

**Phase 2 - Migrate (data synchronization):**
```sql
-- Backfill existing data
UPDATE users SET email_address = email WHERE email_address IS NULL;
```
Deploy code that reads from the new column. Both columns are in sync.

**Phase 3 - Contract (remove old, now safe):**
```sql
-- Remove old column - no running code references it
ALTER TABLE users DROP COLUMN email;
```

Each phase is a separate migration and a separate deployment. Never combine them.

#### Online Schema Changes for MySQL

MySQL's built-in `ALTER TABLE ... ALGORITHM=INPLACE, LOCK=NONE` works for many operations in MySQL 8.0+, but for large tables or operations that require table copies:

**gh-ost (GitHub Online Schema Tool):**

**Template:** `templates/gh-ost-online-schema-change.sh`
gh-ost example with replica throttling, chunk sizing, and lag control for online column addition.

- Creates a ghost table, copies data in chunks, applies binlog changes, then swaps
- Does NOT use triggers (unlike pt-osc)
- Can be paused/resumed/cancelled at any time
- Test with `--test-on-replica` first

**pt-online-schema-change (Percona Toolkit):**

**Template:** `templates/pt-online-schema-change.sh`
pt-osc example with lag throttling, chunk sizing, and critical load cutoff.

- Uses triggers to keep old and new tables in sync
- Well-tested, more mature than gh-ost
- Cannot run two pt-osc operations on the same table simultaneously

#### PostgreSQL Concurrent Operations

**Template:** `templates/pg-concurrent-operations.sql`
Non-blocking index creation, foreign key validation, and NOT NULL addition patterns for PostgreSQL.

#### Blue-Green Database Deployments

For high-stakes migrations where rollback must be instantaneous:

1. **Create "green" database** as a clone of "blue" (production) using snapshot or replication
2. **Apply migrations** to green database only
3. **Run application test suite** against green database
4. **Switch traffic** by updating connection string / DNS / proxy routing
5. **Keep blue database** available for instant rollback for a defined window (e.g., 1 hour)
6. After confidence period, decommission blue

This approach is expensive (two full databases) and only warranted for the riskiest migrations. Often used in combination with read-replica promotion.

---

### Step 6: Data Migration Strategies

#### Backfill Scripts with Batching and Progress Tracking

Never run unbounded `UPDATE` on large tables - it will lock the entire table and potentially exhaust WAL / binlog space.

**Batched backfill pattern (SQL):**

**Template:** `templates/batched-backfill.sql`
PostgreSQL batched backfill with SKIP LOCKED, progress tracking, and replication-friendly pauses.

**Batched backfill pattern (application code - Knex example):**

**Template:** `templates/batched-backfill-knex.js`
Knex-based batched backfill with progress logging and I/O throttling.

#### Data Transformation During Migration

When a migration requires transforming data (not just moving it), embed the transformation in the migration but keep it separate from DDL:

**Template:** `templates/data-transformation-migration.sql`
Four-step DDL + data transformation pattern: add column, transform, constrain, and deferred cleanup.

#### ETL Within Migrations

For complex data restructuring (normalizing denormalized data, splitting tables):

```sql
-- Normalize: extract addresses from users into a new addresses table
INSERT INTO addresses (user_id, street, city, state, zip, created_at)
SELECT id, address_street, address_city, address_state, address_zip, NOW()
FROM users
WHERE address_street IS NOT NULL
ON CONFLICT (user_id) DO NOTHING;  -- Idempotent
```

#### Idempotent Migrations (Safe to Re-Run)

Write migrations so they can be executed multiple times without error or unintended side effects:

**Template:** `templates/idempotent-migrations-pg.sql`
PostgreSQL idempotent patterns for tables, columns, indexes, constraints, and data backfills.

For MySQL, use similar patterns:
```sql
-- MySQL idempotent column add (via procedure or conditional in application)
SET @col_exists = (SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'users' AND column_name = 'phone');
SET @sql = IF(@col_exists = 0, 'ALTER TABLE users ADD COLUMN phone VARCHAR(20)', 'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
```

---

### Step 7: Multi-Database Specifics

#### PostgreSQL-Specific

**Concurrent operations** (covered above in zero-downtime section).

**Table partitioning:**

**Template:** `templates/pg-table-partitioning.sql`
PostgreSQL range partitioning: create partitioned table, add partitions, and attach existing tables.

**Row-Level Security (RLS):**

**Template:** `templates/pg-row-level-security.sql`
Enable RLS, create tenant isolation policy, and force RLS for table owner.

**Advisory locks for migration coordination:**
```sql
-- Prevent concurrent migration runs
SELECT pg_advisory_lock(12345);
-- ... run migration ...
SELECT pg_advisory_unlock(12345);
```

#### MySQL-Specific

**Online DDL (MySQL 8.0+):**

**Template:** `templates/mysql-online-ddl.sql`
MySQL 8.0+ INSTANT and INPLACE algorithm examples for column and index additions.

**Partition management:**

**Template:** `templates/mysql-partition-management.sql`
MySQL partition lifecycle: add, drop, and reorganize range partitions.

**MySQL caveats:**
- No transactional DDL - each `ALTER TABLE` implicitly commits. Rollback of multi-step migrations is not atomic.
- `RENAME COLUMN` requires MySQL 8.0+ - use `CHANGE COLUMN` on older versions.
- Foreign key checks can slow migrations: `SET FOREIGN_KEY_CHECKS = 0;` before bulk operations, but re-enable immediately after and verify integrity.

#### SQLite Limitations and Workarounds

SQLite has very limited `ALTER TABLE` support:
- Can ADD COLUMN (with restrictions: no PRIMARY KEY, no UNIQUE, must have default or be nullable)
- Cannot DROP COLUMN (before 3.35.0), RENAME COLUMN (before 3.25.0), or ALTER column type

**The "12-step" table rebuild workaround:**

**Template:** `templates/sqlite-table-rebuild.sql`
SQLite table rebuild: create new table, copy data, drop old, rename, and recreate indexes.

**Important**: This process invalidates any open references to the old table. In WAL mode, readers may see briefly inconsistent state. Always run inside a transaction.

#### MongoDB Schema Validation Migrations

MongoDB is schemaless, but `jsonSchema` validation provides guardrails:

**Template:** `templates/mongodb-schema-validation.js`
MongoDB jsonSchema validation: add validation with warn level, backfill missing fields, then tighten to strict/error.

**Index creation in MongoDB:**
```javascript
// Background index build (default in MongoDB 4.2+, but explicit for clarity)
db.users.createIndex({ email: 1 }, { unique: true, background: true });

// Partial indexes to reduce size
db.orders.createIndex(
  { status: 1, createdAt: -1 },
  { partialFilterExpression: { status: "pending" } }
);
```

#### Redis Data Structure Migrations

Redis has no schema, but data structure changes require migration scripts:

**Template:** `templates/redis-data-migration.py`
Python script migrating Redis flat keys to hash structures using SCAN and pipelines.

Key considerations:
- Use `SCAN` (not `KEYS`) to iterate - `KEYS` blocks the server on large datasets
- Use pipelines to batch operations and reduce round-trips
- Set TTLs on migrated keys if the old keys had TTLs
- Consider running during low-traffic periods - Redis is single-threaded

---

### Step 8: Migration Testing

#### Dry-Run Against Production Clone

Never test migrations against production directly. Create a clone:

**Template:** `templates/dry-run-production-clone.sh`
PostgreSQL production clone setup for migration dry-run testing.

For realistic testing, the clone should have representative row counts. Schema-only is useful for DDL testing, but data-dependent migrations need actual data.

#### Rollback Testing

**Every migration should be tested in both directions:**

```bash
# Apply
npx knex migrate:latest
# Verify schema matches expected state
# Rollback
npx knex migrate:rollback
# Verify schema returns to previous state
# Re-apply to confirm idempotency
npx knex migrate:latest
```

For migrations that cannot be rolled back (e.g., data loss by design), document this explicitly:

**Template:** `templates/irreversible-migration-knex.js`
Knex down-migration pattern that throws an explicit error for irreversible migrations.

#### Data Integrity Validation Queries

Run before and after migration to verify no data corruption:

**Template:** `templates/data-integrity-validation.sql`
Pre/post migration validation: row counts, null checks, referential integrity, and constraint validation.

#### Before/After Schema Diffing

Capture schema state before and after to verify the migration did exactly what was expected:

**Template:** `templates/schema-diffing.sh`
Before/after schema diffing for PostgreSQL, MySQL, and Prisma.

#### Migration Performance Benchmarking

For migrations on large tables, estimate duration before running in production:

**Template:** `templates/migration-performance-benchmark.sql`
PostgreSQL table size and row count queries for estimating migration duration.

Rule of thumb timing estimates (varies heavily by hardware):
- Adding a nullable column with no default: instant on PostgreSQL 11+, instant on MySQL 8.0.12+ (ALGORITHM=INSTANT)
- Adding a column with a default: instant on PostgreSQL 11+ (stored in catalog), requires table rewrite on PostgreSQL <11
- Creating an index: ~1-5 seconds per million rows (B-tree, single column, SSD)
- `CREATE INDEX CONCURRENTLY`: 2-3x slower than regular index creation but does not lock
- Full table rewrite (`ALTER TYPE`): ~5-15 seconds per million rows depending on row width
- Backfill UPDATE in batches: throughput of ~10K-50K rows/second depending on indexes and row size

---

### Step 9: Seed Data Management

#### Environment-Specific Seeds

Maintain separate seed files for different environments:

```
seeds/
  common/            # Shared across all environments
    001_roles.ts
    002_permissions.ts
  development/       # Developer-friendly fake data
    001_test_users.ts
    002_sample_orders.ts
  staging/           # Mirrors production reference data
    001_feature_flags.ts
  production/        # Only essential reference data
    001_system_config.ts
    002_default_roles.ts
```

**Seed runner pattern:**

**Template:** `templates/seed-runner-pattern.js`
Knex seed runner that loads common and environment-specific seeds in sorted order.

#### Seed Dependencies and Ordering

Seeds often depend on each other (users before orders, roles before role-assignments). Enforce ordering with numeric prefixes and validate dependencies:

**Template:** `templates/seed-dependencies.js`
Knex seed files with dependency declarations and idempotent inserts using onConflict.

#### Incremental Seeding (Add New Seeds Without Re-Running Old)

Track which seeds have been applied, similar to migration tracking:

```sql
CREATE TABLE IF NOT EXISTS seed_history (
  name VARCHAR(255) PRIMARY KEY,
  applied_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Template:** `templates/incremental-seeding.js`
Knex incremental seed runner with seed_history tracking and transactional application.

#### Seed Data Versioning

When seed data must change (e.g., a new required role is added), create a new seed rather than modifying an old one:

```
seeds/production/
  001_default_roles.ts           # Original: admin, user
  005_add_viewer_role.ts         # Added later: viewer
  012_add_billing_role.ts        # Added later: billing
```

Each seed is idempotent (uses `ON CONFLICT ... DO NOTHING` or `INSERT ... WHERE NOT EXISTS`) so the full sequence can run on a fresh database.

---

### Step 10: Schema Drift Detection

#### Compare Running Database Against Migration State

Schema drift occurs when the database schema diverges from what the migrations define - usually from manual DDL changes, emergency fixes, or ORM `synchronize` usage.

**Prisma:**
```bash
# Detect drift (compares database schema to migration history)
npx prisma migrate diff \
  --from-migrations prisma/migrations \
  --to-schema-datasource prisma/schema.prisma

# Or check for drift status
npx prisma migrate status
```

**Django:**
```bash
# Detect unapplied migrations and model-vs-database differences
python manage.py showmigrations
python manage.py migrate --check  # Exit code 1 if unapplied migrations exist
```

**Manual drift detection (PostgreSQL):**

**Template:** `templates/manual-drift-detection-pg.sql`
Query information_schema columns and compare schema dumps to detect drift.

#### Detect Manual Schema Changes

Check for DDL executed outside of the migration system:

**Template:** `templates/detect-manual-schema-changes.sql`
PostgreSQL query listing all public schema objects (tables, indexes, views) for comparison against migration files.

Then compare this list against the objects defined in migration files.

#### Generate Corrective Migrations

When drift is detected, generate a migration that reconciles the database with the desired state:

```bash
# Prisma: pull current DB state into schema, then generate a migration from the diff
npx prisma db pull  # Updates schema.prisma to match the database
# Manually review changes in schema.prisma
# Revert schema.prisma to desired state
# Generate migration for the difference:
npx prisma migrate dev --name fix_drift --create-only
```

**Alembic:**
```bash
# Autogenerate will detect differences between models and database
alembic revision --autogenerate -m "fix_schema_drift"
# Review carefully - autogenerate may misinterpret some changes
```

---

### Step 11: Disaster Recovery

#### Pre-Migration Backup Verification

Before any destructive migration, verify that a valid backup exists and can be restored:

**Template:** `templates/pre-migration-backup.sh`
PostgreSQL and MySQL backup creation, verification, and test restore procedures.

#### Migration Failure Recovery Procedures

**Scenario 1: Migration fails partway through (transactional DDL - PostgreSQL)**
- PostgreSQL wraps migration in a transaction by default (for most tools)
- Failure causes automatic rollback - no manual intervention needed
- Verify: `SELECT * FROM schema_migrations ORDER BY version DESC LIMIT 5;`

**Scenario 2: Migration fails partway through (non-transactional DDL - MySQL)**
- MySQL commits each DDL statement independently
- If migration fails after step 3 of 5, steps 1-3 are committed
- Recovery options:
  1. Fix the issue and re-run (if migration is idempotent)
  2. Manually execute remaining steps
  3. Manually reverse steps 1-3 and start over
  4. Restore from backup
- Document which step failed and what state the database is in

**Scenario 3: Migration succeeds but application breaks**
```bash
# Immediate: roll back the migration
npx prisma migrate rollback   # or equivalent

# If rollback migration doesn't exist or fails:
# Option A: Deploy previous application version (revert the code deployment)
# Option B: Manually reverse the DDL changes
# Option C: Restore from pre-migration backup (last resort - causes data loss for writes since backup)
```

#### Partial Migration Rollback

When a migration contains multiple independent changes and only some need to be reverted:

```sql
-- Don't rollback the entire migration. Instead, write a targeted fix migration:
-- If the migration added columns A, B, C and column C is causing issues:
ALTER TABLE users DROP COLUMN c;
-- Update migration tracking to note the partial rollback (as a comment or metadata)
```

#### Point-in-Time Recovery Coordination

For the worst case - a migration corrupted or deleted critical data:

**Template:** `templates/point-in-time-recovery.sh`
PostgreSQL WAL-based and MySQL binlog-based point-in-time recovery procedures.

**Critical**: Point-in-time recovery loses all writes between the recovery point and now. Coordinate with the team and consider extracting just the affected data from the recovered database rather than fully replacing production.

---

### Step 12: Apply or Review

- Show the migration SQL/code for review - **always show before applying**
- If the migration touches tables over 100K rows, show the estimated impact (lock time, disk space)
- If user confirms, run the migration
- Monitor during execution:
  - Watch for lock wait timeouts
  - Monitor replication lag (if applicable)
  - Watch connection count
- Verify migration status: `npx prisma migrate status`, `npx knex migrate:status`, etc.
- Run data integrity validation queries (Step 8)
- Check that the schema is in the expected state

### Step 13: Report

**Template:** `templates/migration-report.md`
Structured migration report covering schema change, safety checks, testing, status, disaster recovery, and follow-up tasks.

---

## Configuration

Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:

| Setting | Type | Default | Description |
|---|---|---|---|
| `autoApply` | boolean | `false` | Apply migration after generation (default: review first) |
| `safetyLevel` | `"strict"` \| `"normal"` | `"strict"` | Strict flags ALL destructive operations |
| `namingConvention` | string | `"YYYYMMDD_description"` | Migration naming pattern |
| `backupBeforeDestructive` | boolean | `true` | Require backup verification before destructive migrations |
| `maxLockWaitSeconds` | number | `5` | Maximum acceptable lock wait time before suggesting online DDL |
| `largeTabelThreshold` | number | `100000` | Row count above which online DDL tools are recommended |
| `replicationLagThresholdMs` | number | `10000` | Max acceptable replication lag during migration |
| `seedEnvironment` | string | `"development"` | Which seed set to apply by default |
| `dryRunBeforeApply` | boolean | `false` | Run migration against a clone before applying to target |

---

## Quick Reference: Decision Matrix

| Situation | Approach |
|---|---|
| Adding a nullable column | Direct `ALTER TABLE` - safe and fast on all engines |
| Adding a column with default | Direct on PostgreSQL 11+ / MySQL 8.0.12+ (instant). Table rewrite on older versions - use online DDL tools for large tables. |
| Adding an index on a large table | `CREATE INDEX CONCURRENTLY` (PG), `ALGORITHM=INPLACE, LOCK=NONE` (MySQL), or online DDL tool |
| Renaming a column | Expand-contract: add new → backfill → deploy code → drop old |
| Dropping a column | Deploy code that stops using it first, then drop in a separate migration |
| Changing column type | Add new column → backfill with cast → update code → drop old |
| Adding NOT NULL to existing column | Add CHECK constraint as NOT VALID → validate → set NOT NULL (PG). Backfill first on MySQL. |
| Adding foreign key on large table | `NOT VALID` then `VALIDATE CONSTRAINT` (PG). Online DDL tool for MySQL. |
| Splitting a table | ETL migration: create new table → backfill → update code → drop old |
| Large data backfill | Batched updates with progress tracking and replication lag monitoring |
| Emergency schema fix in production | Fix the issue, then generate a corrective migration to match. Never leave drift. |
