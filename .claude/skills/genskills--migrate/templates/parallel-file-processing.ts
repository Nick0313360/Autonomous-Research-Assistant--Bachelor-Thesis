import { Worker } from 'worker_threads';
import { cpus } from 'os';

const NUM_WORKERS = cpus().length;
const files = getAllFilesToMigrate();
const chunks = chunkArray(files, NUM_WORKERS);

await Promise.all(chunks.map((chunk, i) =>
  new Promise((resolve, reject) => {
    const worker = new Worker('./migrate-worker.js', { workerData: chunk });
    worker.on('message', resolve);
    worker.on('error', reject);
  })
));
