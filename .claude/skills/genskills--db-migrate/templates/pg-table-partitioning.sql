-- Create partitioned table (PostgreSQL 10+)
CREATE TABLE events (
  id BIGSERIAL,
  event_type TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  payload JSONB
) PARTITION BY RANGE (created_at);

-- Create partitions
CREATE TABLE events_2025_q1 PARTITION OF events
  FOR VALUES FROM ('2025-01-01') TO ('2025-04-01');

CREATE TABLE events_2025_q2 PARTITION OF events
  FOR VALUES FROM ('2025-04-01') TO ('2025-07-01');

-- Attach existing table as partition (must match schema and constraints)
ALTER TABLE events ATTACH PARTITION events_legacy
  FOR VALUES FROM ('2020-01-01') TO ('2025-01-01');
