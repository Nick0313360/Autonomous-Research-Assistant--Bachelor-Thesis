-- Instant column add (MySQL 8.0.12+ - only for adding columns at the end)
ALTER TABLE users ADD COLUMN phone VARCHAR(20), ALGORITHM=INSTANT;

-- In-place operations (no table copy, minimal locking)
ALTER TABLE users ADD INDEX idx_email (email), ALGORITHM=INPLACE, LOCK=NONE;

-- Operations that STILL require table copy in MySQL 8.0:
-- Changing column type, dropping a primary key, converting charset
-- Use gh-ost or pt-online-schema-change for these on large tables
