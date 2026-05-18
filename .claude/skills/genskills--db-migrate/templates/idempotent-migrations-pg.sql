-- Tables
CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  action TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Columns (PostgreSQL - check before adding)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'users' AND column_name = 'phone'
  ) THEN
    ALTER TABLE users ADD COLUMN phone VARCHAR(20);
  END IF;
END $$;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);

-- Constraints (check pg_constraint)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'users_email_unique'
  ) THEN
    ALTER TABLE users ADD CONSTRAINT users_email_unique UNIQUE (email);
  END IF;
END $$;

-- Data backfills (use ON CONFLICT or WHERE NOT EXISTS)
INSERT INTO settings (key, value)
VALUES ('feature_x', 'enabled')
ON CONFLICT (key) DO NOTHING;
