-- 1. Create new table with desired schema
CREATE TABLE users_new (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  created_at TEXT DEFAULT (datetime('now'))
);
-- 2. Copy data
INSERT INTO users_new (id, name, email, created_at)
  SELECT id, name, email, created_at FROM users;
-- 3. Drop old table
DROP TABLE users;
-- 4. Rename new table
ALTER TABLE users_new RENAME TO users;
-- 5. Recreate indexes and triggers
CREATE INDEX idx_users_email ON users (email);
