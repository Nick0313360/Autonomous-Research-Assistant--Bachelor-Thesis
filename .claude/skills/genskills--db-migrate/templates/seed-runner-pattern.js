async function runSeeds(knex, environment) {
  const commonSeeds = await glob('seeds/common/*.ts');
  const envSeeds = await glob(`seeds/${environment}/*.ts`);
  const allSeeds = [...commonSeeds, ...envSeeds].sort();

  for (const seedFile of allSeeds) {
    const seed = require(seedFile);
    await seed.run(knex);
    console.log(`Seeded: ${path.basename(seedFile)}`);
  }
}
