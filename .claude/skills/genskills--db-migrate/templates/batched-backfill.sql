-- PostgreSQL example: backfill in batches of 5000
DO $$
DECLARE
  batch_size INT := 5000;
  affected INT;
  total_processed INT := 0;
BEGIN
  LOOP
    WITH batch AS (
      SELECT id FROM users
      WHERE email_normalized IS NULL
      LIMIT batch_size
      FOR UPDATE SKIP LOCKED
    )
    UPDATE users
    SET email_normalized = lower(trim(email))
    FROM batch
    WHERE users.id = batch.id;

    GET DIAGNOSTICS affected = ROW_COUNT;
    total_processed := total_processed + affected;
    RAISE NOTICE 'Processed % rows (% total)', affected, total_processed;

    EXIT WHEN affected = 0;
    PERFORM pg_sleep(0.1);  -- Brief pause to reduce replication lag
  END LOOP;
END $$;
