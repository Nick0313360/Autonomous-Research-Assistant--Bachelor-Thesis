async function backfillEmailNormalized(knex) {
  const BATCH_SIZE = 5000;
  let totalProcessed = 0;
  let affected;

  do {
    affected = await knex.raw(`
      WITH batch AS (
        SELECT id FROM users WHERE email_normalized IS NULL LIMIT ?
      )
      UPDATE users SET email_normalized = lower(trim(email))
      FROM batch WHERE users.id = batch.id
    `, [BATCH_SIZE]);

    totalProcessed += affected.rowCount;
    console.log(`Backfill progress: ${totalProcessed} rows processed`);

    // Pause to limit replication lag and I/O
    await new Promise(r => setTimeout(r, 100));
  } while (affected.rowCount > 0);

  console.log(`Backfill complete: ${totalProcessed} total rows`);
}
