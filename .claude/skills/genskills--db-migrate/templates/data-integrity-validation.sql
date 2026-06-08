-- Row counts (should match before and after for non-destructive migrations)
SELECT 'users' AS table_name, count(*) AS row_count FROM users
UNION ALL
SELECT 'orders', count(*) FROM orders;

-- Null checks on columns that should be populated
SELECT count(*) AS null_email_count FROM users WHERE email IS NULL;

-- Referential integrity (even if foreign keys exist, verify)
SELECT o.id AS orphaned_order_id
FROM orders o
LEFT JOIN users u ON o.user_id = u.id
WHERE u.id IS NULL;

-- Constraint validation
SELECT count(*) FROM users WHERE length(email) > 255;
