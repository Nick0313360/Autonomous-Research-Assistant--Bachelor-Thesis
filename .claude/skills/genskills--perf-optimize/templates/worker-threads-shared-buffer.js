const { Worker, isMainThread, parentPort, workerData } = require('worker_threads');

if (isMainThread) {
  const sharedBuffer = new SharedArrayBuffer(1024);
  const worker = new Worker(__filename, { workerData: { sharedBuffer } });
  // Both main and worker can read/write via typed array views
  const view = new Int32Array(sharedBuffer);
  Atomics.store(view, 0, 42);
} else {
  const view = new Int32Array(workerData.sharedBuffer);
  const val = Atomics.load(view, 0); // 42
}
