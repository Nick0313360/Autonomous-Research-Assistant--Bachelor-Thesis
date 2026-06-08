# V8 CPU profiler
node --prof app.js
node --prof-process isolate-*.log > processed.txt

# Trace events (scheduling, GC, compilation)
node --trace-event-categories v8,node.async_hooks app.js
# Open chrome://tracing and load the generated JSON

# Inspect event loop utilization
node -e "
const { monitorEventLoopDelay } = require('perf_hooks');
const h = monitorEventLoopDelay({ resolution: 20 });
h.enable();
setTimeout(() => {
  console.log('Event loop delay p50:', h.percentile(50), 'ns');
  console.log('Event loop delay p99:', h.percentile(99), 'ns');
  console.log('Mean:', h.mean, 'ns');
}, 5000);
"
