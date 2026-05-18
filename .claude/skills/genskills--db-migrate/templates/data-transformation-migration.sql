-- Step 1: DDL (add new structure)
ALTER TABLE orders ADD COLUMN total_cents BIGINT;

-- Step 2: Data transformation
UPDATE orders SET total_cents = ROUND(total_dollars * 100)::BIGINT;

-- Step 3: DDL (enforce constraints on new structure)
ALTER TABLE orders ALTER COLUMN total_cents SET NOT NULL;

-- Step 4: DDL (clean up old structure - in a SEPARATE migration after code deploys)
-- ALTER TABLE orders DROP COLUMN total_dollars;
