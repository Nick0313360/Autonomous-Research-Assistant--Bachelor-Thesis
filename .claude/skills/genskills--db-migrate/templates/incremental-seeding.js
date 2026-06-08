async function runIncrementalSeeds(knex, seedDir) {
  const applied = await knex('seed_history').pluck('name');
  const allSeeds = (await glob(`${seedDir}/*.ts`)).sort();
  const pendingSeeds = allSeeds.filter(s => !applied.includes(path.basename(s)));

  for (const seedFile of pendingSeeds) {
    const seed = require(seedFile);
    await knex.transaction(async (trx) => {
      await seed.run(trx);
      await trx('seed_history').insert({ name: path.basename(seedFile) });
    });
    console.log(`Applied seed: ${path.basename(seedFile)}`);
  }
}
