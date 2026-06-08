// Step 1: Generate snapshots from old code (run once, commit)
import { writeFileSync } from 'fs';
const scenarios = loadTestScenarios();
const snapshots = scenarios.map(s => ({ input: s, output: oldImplementation(s) }));
writeFileSync('migration-snapshots.json', JSON.stringify(snapshots, null, 2));

// Step 2: Verify new code matches snapshots
import snapshots from './migration-snapshots.json';
describe('migration parity', () => {
  snapshots.forEach(({ input, output }, i) => {
    it(`scenario ${i}`, () => {
      expect(newImplementation(input)).toEqual(output);
    });
  });
});
