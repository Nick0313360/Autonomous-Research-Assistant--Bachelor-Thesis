-- Non-blocking index creation (takes longer but no lock)
CREATE INDEX CONCURRENTLY idx_users_email ON users (email);

-- Non-blocking constraint validation (two-step)
ALTER TABLE users ADD CONSTRAINT fk_org
  FOREIGN KEY (org_id) REFERENCES orgs(id)
  NOT VALID;  -- Instant, only checks new rows

ALTER TABLE users VALIDATE CONSTRAINT fk_org;  -- Scans table, but does not lock writes

-- Non-blocking NOT NULL (PostgreSQL 12+)
-- Add a CHECK constraint as NOT VALID, validate it, then add NOT NULL
ALTER TABLE users ADD CONSTRAINT users_email_nn CHECK (email IS NOT NULL) NOT VALID;
ALTER TABLE users VALIDATE CONSTRAINT users_email_nn;
-- PostgreSQL 12+ recognizes the validated check and adds NOT NULL without a full scan:
ALTER TABLE users ALTER COLUMN email SET NOT NULL;
ALTER TABLE users DROP CONSTRAINT users_email_nn;
