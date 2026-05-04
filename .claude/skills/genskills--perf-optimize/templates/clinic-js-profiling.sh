# Doctor: identify I/O vs CPU vs event loop bottlenecks
npx clinic doctor -- node server.js
# Then load-test the server, Ctrl+C to generate report

# Flame: CPU flame graph
npx clinic flame -- node server.js

# Bubbleprof: async operations visualization
npx clinic bubbleprof -- node server.js

# Heap profiler: memory allocation tracking
npx clinic heapprofile -- node server.js
