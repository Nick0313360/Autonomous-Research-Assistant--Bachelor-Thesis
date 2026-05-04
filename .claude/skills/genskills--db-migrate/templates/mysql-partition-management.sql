-- Add a new partition (for RANGE partitioning)
ALTER TABLE events ADD PARTITION (
  PARTITION p_2025_q2 VALUES LESS THAN ('2025-07-01')
);

-- Drop old partition (instant, much faster than DELETE)
ALTER TABLE events DROP PARTITION p_2023_q1;

-- Reorganize partitions
ALTER TABLE events REORGANIZE PARTITION p_future INTO (
  PARTITION p_2025_q3 VALUES LESS THAN ('2025-10-01'),
  PARTITION p_future VALUES LESS THAN MAXVALUE
);
