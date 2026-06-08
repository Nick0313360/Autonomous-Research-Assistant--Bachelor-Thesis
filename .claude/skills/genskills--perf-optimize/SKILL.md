---
name: genskills:perf-optimize
description: >
  Analyze and optimize code performance - identify bottlenecks,
  reduce bundle size, optimize queries, improve load times.
  Triggers on: "optimize", "performance", "speed up", "slow",
  "bundle size", "make faster", "reduce load time".
user-invocable: true
argument-hint: "[area: frontend|backend|database|bundle|memory|concurrency|network|rendering|build|runtime|observability|all]"
allowed-tools: "Read, Edit, Grep, Glob, WebFetch, Bash(npm run *), Bash(npm test*), Bash(npx *), Bash(node *), Bash(python *), Bash(go *)"
genskills-version: "1.4.2"
genskills-category: "development"
genskills-depends: []
---

# Performance Optimizer

Analyze and optimize code performance across the entire stack - from memory layout and concurrency to rendering, network, database, build pipelines, and runtime execution.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any performance guidelines documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Identify the tech stack to know which optimizations are applicable
- Check for existing performance budgets, Lighthouse CI configs, or monitoring dashboards

### Step 1: Identify Focus Area
From `$ARGUMENTS` (default: "all"):
- **frontend**: React/Vue/Svelte render performance, bundle size, lazy loading
- **backend**: API response times, database queries, caching, concurrency
- **database**: Query optimization, N+1, indexing, connection pooling, query plans
- **bundle**: Bundle size analysis, tree shaking, code splitting, build tooling
- **memory**: Memory leak detection, heap analysis, garbage collection tuning
- **concurrency**: Worker threads, async patterns, connection pooling, backpressure
- **network**: HTTP/2, request batching, caching strategies, compression, prefetching
- **rendering**: Virtual scrolling, lazy rendering, CSS containment, SSR, hydration
- **build**: Build tool migration, module federation, persistent caching, chunk splitting
- **runtime**: JIT/AOT, WebAssembly, edge computing, streaming responses
- **observability**: Metrics, performance budgets, Core Web Vitals, RUM
- **all**: Full-stack analysis across every area

---

## Step 2: Analyze (by area)

### Frontend

- Check for unnecessary re-renders:
  - Components without `React.memo` that receive new object/array props each render
  - Missing `useMemo` for expensive computations
  - Missing `useCallback` for functions passed as props to memoized children
  - State updates that trigger renders in unrelated component subtrees
  - Context providers with values that change reference on every render
- Find large component trees that could be code-split with `React.lazy`/`dynamic()`
- Check image optimization: unoptimized formats (use WebP/AVIF), missing width/height, missing lazy loading, no next/image usage
- Check for layout shifts (CLS): elements without explicit dimensions, fonts without `font-display: swap`
- Find blocking resources: large synchronous scripts, render-blocking CSS, undeferred third-party scripts

### Backend

- Find N+1 query patterns (loops with DB calls inside)
- Check for missing caching opportunities (repeated identical queries, static data)
- Identify synchronous blocking operations that could be async (file I/O, HTTP calls)
- Check for unnecessary data fetching: over-fetching (selecting all columns), under-batching
- Find missing pagination on list endpoints
- Check for missing response compression (gzip/brotli)
- Verify streaming is used for large response payloads where appropriate
- Check middleware ordering - heavy middleware should not run on routes that do not need it

---

### Memory Optimization

**JavaScript / Node.js**:
- Detect memory leak patterns:
  - Event listeners that are never removed (especially on long-lived objects or globals)
  - Closures that capture large scopes unintentionally
  - Growing `Map`/`Set`/`Array` collections that are never pruned
  - Detached DOM nodes held by references in component state or global caches
  - `setInterval`/`setTimeout` callbacks that hold references after component unmount
- Use `WeakRef` and `WeakMap` for caches that should not prevent garbage collection:
  ```js
  // Instead of: const cache = new Map();
  const cache = new WeakMap(); // keys are GC'd when no other references exist

  // For optional references:
  const ref = new WeakRef(largeObject);
  const obj = ref.deref(); // returns undefined if GC'd
  ```
- Use `FinalizationRegistry` to clean up resources when objects are collected:
  ```js
  const registry = new FinalizationRegistry((heldValue) => {
    // cleanup external resource associated with heldValue
  });
  registry.register(targetObject, resourceId);
  ```
- Check for unbounded caches - every cache must have a max size and eviction policy (LRU, TTL)

**Profiling commands - Node.js heap analysis**:

**Template:** `templates/node-heap-profiling.sh` - Heap snapshot capture, GC tracing, clinic.js analysis, and Chrome DevTools inspection commands

**Heap snapshot comparison workflow**:
1. Take snapshot before the operation
2. Perform the suspected leaking operation multiple times
3. Take snapshot after
4. Compare retained sizes - look for objects growing between snapshots
5. Focus on the "Comparison" view, sorted by "# Delta" (objects allocated minus freed)

**V8 memory management considerations**:
- V8 divides the heap into Young Generation (short-lived, ~1-8MB, Scavenge GC) and Old Generation (long-lived, Mark-Sweep/Compact GC)
- Objects surviving two Scavenge cycles get promoted to Old Generation
- Frequent allocations of short-lived objects increase Scavenge pauses
- Large arrays and buffers may be allocated directly in Large Object Space
- Use `--expose-gc` and `global.gc()` in test environments to force GC and measure retained memory

**Python memory profiling**:

**Template:** `templates/python-memory-profiling.sh` - tracemalloc, objgraph, memory_profiler, and pympler commands for Python heap analysis

**Go pprof heap analysis**:

**Template:** `templates/go-pprof-heap-analysis.sh` - Go pprof commands for heap capture, comparison, allocation analysis, and flame graphs

---

### Concurrency Optimization

**Node.js Worker Threads**:
- Use `worker_threads` for CPU-intensive tasks (image processing, crypto, parsing large files)
- Keep the main event loop free for I/O - offload any computation over ~50ms
- Use `SharedArrayBuffer` for zero-copy data sharing between threads:

  **Template:** `templates/worker-threads-shared-buffer.js` - Worker threads example with SharedArrayBuffer and Atomics for zero-copy data sharing
- Use a worker pool (e.g., `piscina` or `workerpool`) instead of spawning workers per request
- Transfer large `ArrayBuffer` objects instead of copying: `worker.postMessage(buffer, [buffer])`

**Web Workers (browser)**:
- Offload heavy computation to Web Workers to prevent UI jank (>16ms blocks)
- Use `Comlink` for ergonomic worker communication:
  ```js
  // worker.js
  import * as Comlink from 'comlink';
  const api = { heavyCalc(data) { /* ... */ return result; } };
  Comlink.expose(api);

  // main.js
  const worker = new Worker('./worker.js', { type: 'module' });
  const api = Comlink.wrap(worker);
  const result = await api.heavyCalc(data);
  ```
- Use `OffscreenCanvas` for rendering work in workers
- SharedArrayBuffer requires cross-origin isolation headers: `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Embedder-Policy: require-corp`

**Connection pooling tuning**:
- Formula for optimal pool size (PostgreSQL): `pool_size = (core_count * 2) + effective_spindle_count`
- For SSDs, start with `pool_size = core_count * 2` and benchmark from there
- Set `idleTimeoutMillis` to release unused connections (typically 10-30 seconds)
- Set `connectionTimeoutMillis` to fail fast when pool is exhausted (typically 5-10 seconds)
- Monitor pool metrics: active connections, waiting requests, idle connections, timeouts
- Avoid a pool per microservice instance exceeding the database `max_connections`

**Async queue management and backpressure**:
- Use bounded queues to prevent memory exhaustion under load
- Implement backpressure: if the queue is full, reject or slow down the producer
- Node.js streams have built-in backpressure - always check `writable.write()` return value and wait for `'drain'`
- Use `p-limit`, `p-queue`, or `bottleneck` for concurrency limiting:
  ```js
  import pLimit from 'p-limit';
  const limit = pLimit(10); // max 10 concurrent
  const results = await Promise.all(
    urls.map(url => limit(() => fetch(url)))
  );
  ```

**Go goroutine optimization**:

**Template:** `templates/go-goroutine-concurrency.go` - Semaphore pattern, errgroup with concurrency limits, and goroutine profiling commands

**Python asyncio / multiprocessing**:

**Template:** `templates/python-asyncio-multiprocessing.py` - asyncio with semaphore-limited concurrency and ProcessPoolExecutor for CPU-bound parallelism

---

### Network Optimization

**HTTP/2 multiplexing**:
- Ensure the server supports HTTP/2 - one TCP connection can carry many requests in parallel
- With HTTP/2, domain sharding is an anti-pattern - consolidate assets to one origin
- HTTP/2 Server Push is deprecated in most browsers - use `103 Early Hints` instead
- Use `preload` link headers to hint critical resources before the HTML is fully parsed

**Request batching and deduplication**:
- Batch multiple API calls into a single request where the backend supports it (e.g., GraphQL, REST batch endpoints)
- Deduplicate in-flight requests - if the same URL is already being fetched, return the same promise:
  ```js
  const inFlight = new Map();
  function deduplicatedFetch(url, options) {
    const key = `${options?.method || 'GET'}:${url}`;
    if (inFlight.has(key)) return inFlight.get(key);
    const promise = fetch(url, options).finally(() => inFlight.delete(key));
    inFlight.set(key, promise);
    return promise;
  }
  ```
- Use DataLoader pattern for batching database/API calls within a single request lifecycle

**Prefetching strategies**:
- `<link rel="prefetch">` for resources needed on the next navigation (low priority, uses idle time)
- `<link rel="preload">` for resources needed on the current page (high priority, immediate)
- `<link rel="preconnect">` for third-party origins to establish TCP + TLS early
- `<link rel="dns-prefetch">` as a fallback for browsers that do not support preconnect
- Speculative prefetching on hover/focus: prefetch the target page when the user hovers a link
- Use the Speculation Rules API for prerendering:
  ```html
  <script type="speculationrules">
  { "prerender": [{ "where": { "href_matches": "/product/*" }, "eagerness": "moderate" }] }
  </script>
  ```

**Service worker caching strategies**:
- **Cache-first** (stale-while-revalidate): serve from cache immediately, update in background - best for static assets
- **Network-first**: try network, fall back to cache - best for API data that should be fresh
- **Cache-only**: never hit network - for versioned/immutable assets
- Use Workbox for production-grade service worker caching with precaching manifests and runtime caching routes
- Set appropriate `Cache-Control` headers: `immutable` for hashed assets, `no-cache` for HTML, `max-age` with `stale-while-revalidate` for APIs

**CDN configuration**:
- Cache static assets at the edge with long `max-age` and content-hash filenames for instant invalidation
- Use `Vary` headers correctly to avoid serving wrong cached responses (e.g., `Vary: Accept-Encoding, Accept`)
- Enable Brotli compression at the CDN level (20-30% smaller than gzip for text)
- Configure appropriate TTLs: HTML (short/no-cache), JS/CSS with hash (1 year), images (1 month+), fonts (1 year)
- Use `stale-while-revalidate` and `stale-if-error` for resilience

**API response compression**:
- Enable Brotli (preferred) and gzip as fallback for all text-based responses
- For Node.js, use `compression` middleware or better, handle at the reverse proxy/CDN level
- Compress JSON responses - typical 70-90% reduction on large payloads
- For very large payloads, consider streaming NDJSON or server-sent events instead of buffering

**GraphQL query complexity analysis**:
- Implement query depth limiting to prevent deeply nested queries
- Assign complexity scores to fields and reject queries exceeding a threshold:
  ```js
  // Example complexity rule:
  // Each field = 1 point, each list field = multiplier * child complexity
  // Reject if total > 1000
  ```
- Use persistent queries (query allowlisting) in production to prevent arbitrary queries
- Enable automatic persisted queries (APQ) - client sends hash, server looks up full query
- Use `@defer` and `@stream` directives for incremental delivery of large responses

**Connection keep-alive**:
- Ensure HTTP keep-alive is enabled (default in HTTP/1.1+ but verify proxy configs)
- Set appropriate `Keep-Alive: timeout=N, max=M` values
- For backend-to-backend calls, reuse HTTP agents with keep-alive:
  ```js
  const http = require('http');
  const agent = new http.Agent({ keepAlive: true, maxSockets: 50, maxFreeSockets: 10 });
  // Use this agent for all outgoing requests
  ```

---

### Rendering Optimization

**Virtual scrolling**:
- For lists exceeding ~100 items, use virtual scrolling to render only visible items
- Libraries: `@tanstack/react-virtual`, `react-window`, `react-virtuoso`
- Also applies to tables, grids, and tree views
- Measure item heights dynamically for variable-size items (avoid fixed-height assumptions)

**Intersection Observer for lazy rendering**:
```js
// Defer rendering of off-screen components until they scroll into view
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      renderComponent(entry.target);
      observer.unobserve(entry.target);
    }
  });
}, { rootMargin: '200px' }); // start loading 200px before visible
```
- Use for lazy-loading images, below-the-fold sections, heavy charts/visualizations
- Use `rootMargin` to start loading slightly before the element is visible

**CSS containment**:
```css
/* Tell the browser this element's internals don't affect outside layout */
.card {
  contain: layout style paint; /* or contain: content for layout+style+paint */
}
/* For off-screen elements, use content-visibility for massive rendering savings */
.below-fold-section {
  content-visibility: auto;
  contain-intrinsic-size: auto 500px; /* estimated height to prevent layout jumps */
}
```
- `content-visibility: auto` can skip rendering of off-screen content entirely - 10x+ rendering improvement for long pages
- Always pair with `contain-intrinsic-size` to prevent scroll bar jumping

**`will-change` and compositor-only animations**:
- Only animate `transform` and `opacity` - these run on the GPU compositor thread without triggering layout or paint
- Use `will-change` sparingly and only right before animating - do not set it permanently:
  ```css
  .element:hover { will-change: transform; }
  .element.animating { transform: translateX(100px); transition: transform 300ms; }
  ```
- Avoid animating `width`, `height`, `top`, `left`, `margin`, `padding` - these trigger expensive layout recalculations
- Use `translate`, `scale`, `rotate` individual properties (newer CSS) for more compositable transforms

**React Server Components (RSC)**:
- Move data fetching and heavy rendering to the server - RSC sends serialized UI, not JavaScript
- Keep client components small - only the interactive parts need `"use client"`
- Use RSC for: database queries, markdown rendering, syntax highlighting, content-heavy pages
- Avoid passing large serialized data from server to client components - keep the boundary thin

**Streaming SSR**:
- Use `renderToPipeableStream` (React 18+) to stream HTML to the browser as it renders
- Wrap slow sections in `<Suspense>` with fallbacks - the shell ships immediately, slow parts stream in later
- Streaming reduces Time to First Byte (TTFB) and First Contentful Paint (FCP)
- Compatible with edge runtimes for global low-latency SSR

**Partial hydration and Islands architecture**:
- Hydrate only interactive components - static content needs no JavaScript
- Frameworks: Astro (Islands), Qwik (resumability), Fresh (Deno)
- In Next.js, RSC achieves a similar effect - server components are never hydrated
- For legacy apps, consider progressive hydration: hydrate above-the-fold first, defer the rest
- Islands architecture: static HTML shell with independent interactive "islands" that hydrate independently

---

### Database Advanced Optimization

**Query plan analysis**:

**Template:** `templates/query-plan-analysis.sql` - EXPLAIN ANALYZE examples for PostgreSQL and MySQL with guidance on interpreting query plans

**Indexing strategy**:
- Index columns used in `WHERE`, `JOIN ON`, `ORDER BY`, `GROUP BY`
- Use composite indexes matching your query patterns - column order matters (leftmost prefix rule)
- Use partial indexes for queries that always filter a subset: `CREATE INDEX idx ON orders(created_at) WHERE status = 'active';`
- Use covering indexes to avoid table lookups: include all columns the query selects
- Use expression indexes for computed filters: `CREATE INDEX idx ON users(LOWER(email));`
- Monitor index usage: unused indexes waste write performance and disk
  ```sql
  -- PostgreSQL: find unused indexes
  SELECT indexrelname, idx_scan FROM pg_stat_user_indexes WHERE idx_scan = 0;
  ```

**Materialized views**:

**Template:** `templates/materialized-views.sql` - CREATE MATERIALIZED VIEW example with concurrent refresh strategy
- Use materialized views for dashboards, reports, and any query that aggregates large datasets
- Trade storage and refresh latency for query speed

**Read replicas**:
- Route all read queries (especially heavy reports/analytics) to read replicas
- Use connection-level routing or middleware (e.g., ProxySQL, PgBouncer with routing)
- Be aware of replication lag - for strong consistency, read from primary after writes
- Pattern: write to primary, read from replica, but read from primary within a user's session after their own writes

**Connection pool sizing**:
- PostgreSQL recommended formula: `pool_size = (core_count * 2) + effective_spindle_count`
- For cloud databases, start with `num_app_instances * pool_size_per_instance < db_max_connections - reserved`
- Reserve 10-20% of `max_connections` for superuser/monitoring
- Use PgBouncer in transaction mode for serverless or high-connection-count workloads (reduces connection overhead 10-100x)
- Monitor: `SELECT count(*) FROM pg_stat_activity;` to see active connections

**Cursor-based pagination vs offset**:
```sql
-- OFFSET pagination - gets progressively slower on large tables
SELECT * FROM products ORDER BY id LIMIT 20 OFFSET 10000; -- scans 10,020 rows

-- Cursor-based pagination - consistent performance regardless of page depth
SELECT * FROM products WHERE id > :last_seen_id ORDER BY id LIMIT 20; -- scans 20 rows
```
- Always prefer cursor-based pagination for large tables and infinite scroll UIs
- For multi-column sorting, use composite cursors: `WHERE (created_at, id) > (:last_created_at, :last_id)`
- Offset pagination is acceptable only for small datasets or when the user needs to jump to arbitrary pages

**Denormalization strategies**:
- Store computed aggregates alongside source data (e.g., `comment_count` on the post row)
- Use JSON columns for nested data that is always fetched together (avoids JOINs)
- Maintain denormalized data via database triggers or application-level event handlers
- Consider event sourcing + CQRS for systems where read and write patterns differ drastically

**Caching layers - Redis patterns**:
- **Cache-aside**: application checks cache first, loads from DB on miss, writes to cache
- **Write-through**: application writes to cache and DB simultaneously - cache is always fresh
- **Write-behind**: application writes to cache, cache asynchronously writes to DB - faster writes but risk of data loss
- Use Redis TTL to auto-expire stale data; use cache invalidation on writes for consistency
- Use Redis pipelines to batch multiple commands in one round trip
- Use Redis Lua scripts for atomic read-modify-write operations
- Pattern for preventing cache stampede: use distributed locking (SETNX) so only one process rebuilds on cache miss

**Prepared statements**:
- Prepared statements skip query parsing and planning on repeated calls - significant speedup for hot queries
- In PostgreSQL, use `PREPARE` or driver-level prepared statements (most ORMs support this)
- In Node.js with `pg`, enable prepared statements by passing a `name` to the query:
  ```js
  await client.query({ name: 'get-user', text: 'SELECT * FROM users WHERE id = $1', values: [userId] });
  ```
- Be aware of plan cache bloat - prepared statements with varying parameters may generate sub-optimal generic plans

---

### Bundle and Build Optimization

**Bundle analysis**:
- Check for large dependencies that have lighter alternatives:
  - `moment` -> `dayjs` or `date-fns` (90% size reduction)
  - `lodash` -> `lodash-es` or native methods
  - `axios` -> native `fetch`
  - `uuid` -> `crypto.randomUUID()` (built-in)
  - `classnames` -> `clsx` (smaller)
- Find duplicate dependencies in the bundle
- Verify tree shaking is working (check for barrel file imports like `import { x } from 'huge-lib'`)
- Check for dynamic imports where appropriate (routes, heavy components, optional features)
- Look for dead code that increases bundle size

**SWC/esbuild migration**:
- Replace Babel with SWC for 20-70x faster transpilation
- Replace terser with SWC minify or esbuild minify for 10-100x faster minification
- In Next.js, SWC is default - verify `next.config.js` does not fall back to Babel (presence of `.babelrc` disables SWC)
- For Jest, use `@swc/jest` instead of `ts-jest` or `babel-jest` for 2-5x faster test runs

**Module federation**:
- Share dependencies across micro-frontends at runtime to avoid duplication
- Define shared modules with version constraints to prevent multiple React copies
- Use dynamic remotes for independently deployed micro-frontends
- Consider module federation for large monorepos where independent team deployment is needed

**Persistent caching and incremental builds**:
- Webpack 5: enable `cache: { type: 'filesystem' }` for persistent caching (2-10x faster rebuilds)
- Turbopack: built-in incremental computation - faster than filesystem caching
- TypeScript: use `tsc --incremental` and ensure `tsconfig.json` has `"incremental": true`
- ESLint: use `--cache` flag and `.eslintcache` file

**Tree-shaking verification**:
- Import specific modules, not entire packages: `import debounce from 'lodash/debounce'` instead of `import { debounce } from 'lodash'`
- Verify `sideEffects` in `package.json`:
  ```json
  {
    "sideEffects": false,
    // or for CSS/global files that should not be tree-shaken:
    "sideEffects": ["*.css", "*.global.js"]
  }
  ```
- Barrel files (`index.ts` that re-export everything) defeat tree shaking in many bundlers - import directly from the source module
- Use `/* @__PURE__ */` annotations for function calls that bundlers should consider side-effect-free

**Chunk splitting strategies**:
- Split by route - each page gets its own chunk, loaded on navigation
- Split vendor dependencies into a separate chunk (changes less frequently, better caching)
- Split heavy libraries (e.g., chart libraries, editors) into their own chunks loaded on demand
- Use `maxSize` in webpack to break oversized chunks
- Name chunks explicitly for better caching and debugging:
  ```js
  const Editor = lazy(() => import(/* webpackChunkName: "editor" */ './Editor'));
  ```

---

### Runtime Optimization

**JIT warming**:
- V8 compiles functions to optimized machine code after they are called enough times (hot functions)
- Avoid polymorphic call sites - calling a function with different shapes of objects forces V8 to deoptimize
- Keep hot functions monomorphic: consistent argument types, consistent object shapes
- Avoid `delete` on objects (creates hidden class transitions); use `undefined` assignment instead
- Avoid `arguments` keyword - use rest parameters (`...args`) for V8-friendly code

**AOT compilation**:
- Angular AOT: compile templates at build time to avoid shipping the compiler to the browser
- Svelte: compiles components to imperative DOM operations at build time - zero runtime framework overhead
- Use ahead-of-time compilation for production always; reserve JIT for development only

**WebAssembly for compute-heavy operations**:
- Use WASM for: image/video processing, crypto, physics simulations, compression, parsing
- Compile from Rust (`wasm-pack`), C/C++ (`emscripten`), or Go (`GOOS=js GOARCH=wasm`)
- WASM runs at near-native speed and has predictable performance (no GC pauses)
- Use `SharedArrayBuffer` to share memory between WASM and JavaScript workers
- WASI (WebAssembly System Interface) enables server-side WASM for edge computing

**Edge computing patterns**:
- Move compute to the edge (Cloudflare Workers, Vercel Edge, Deno Deploy) for sub-50ms global latency
- Edge functions are best for: authentication, A/B testing, geolocation routing, personalization, HTML rewriting
- Limitations: no long-running processes, limited CPU time, restricted APIs
- Use edge middleware for request-level logic; keep heavy computation in regional serverless or servers

**Streaming responses**:
- Use `ReadableStream` / `TransformStream` for processing data without buffering entire payloads
- Stream large JSON arrays as NDJSON (newline-delimited JSON) for progressive parsing
- Use server-sent events (SSE) for real-time updates instead of polling
- In Node.js, pipe streams instead of buffering: `readStream.pipe(transformStream).pipe(response)`

---

### Observability Integration

**Custom metrics**:
- Track business-critical performance metrics beyond defaults (e.g., time-to-interactive for key flows, search result latency)
- Use the Performance API for custom marks and measures:
  ```js
  performance.mark('search-start');
  // ... perform search ...
  performance.mark('search-end');
  performance.measure('search-duration', 'search-start', 'search-end');
  const duration = performance.getEntriesByName('search-duration')[0].duration;
  ```
- Report to analytics: `navigator.sendBeacon('/analytics', payload)` (non-blocking, survives page unload)

**Performance budgets**:
- Set concrete limits and fail the build if exceeded:
  ```json
  // In webpack config (performance hints):
  {
    "performance": {
      "maxAssetSize": 250000,
      "maxEntrypointSize": 500000,
      "hints": "error"
    }
  }
  ```
- Use `bundlesize` or `size-limit` packages for CI-enforced size limits:
  ```json
  // package.json
  { "size-limit": [
    { "path": "dist/index.js", "limit": "50 kB" },
    { "path": "dist/vendor.js", "limit": "150 kB" }
  ]}
  ```
- Budget categories: total JS (< 300KB compressed), total CSS (< 50KB), largest image (< 200KB), total page weight (< 1.5MB)

**Core Web Vitals monitoring**:
- **LCP** (Largest Contentful Paint): < 2.5s - optimize critical rendering path, preload hero images, use SSR
- **INP** (Interaction to Next Paint): < 200ms - break up long tasks, use `requestIdleCallback`, avoid layout thrashing
- **CLS** (Cumulative Layout Shift): < 0.1 - set explicit dimensions, use `font-display: swap`, reserve space for dynamic content
- Collect in the field with `web-vitals` library:
  ```js
  import { onLCP, onINP, onCLS } from 'web-vitals';
  onLCP(sendToAnalytics);
  onINP(sendToAnalytics);
  onCLS(sendToAnalytics);
  ```

**Lighthouse CI thresholds**:

**Template:** `templates/lighthouse-ci.yml` - lighthouserc.yml config with performance score, FCP, TTI, and byte weight assertions
```bash
# Run in CI
npx @lhci/cli autorun
```

**Real User Monitoring (RUM) setup**:
- Collect performance data from real users via `PerformanceObserver`:

  **Template:** `templates/rum-performance-observer.js` - PerformanceObserver setup tracking resources, navigation, long tasks, LCP, and layout shifts
- Segment RUM data by: device type, connection speed (`navigator.connection.effectiveType`), geography, page/route
- Set alerts on p75 and p95 thresholds - averages hide tail latency

---

### Profiling Commands Reference

**Node.js profiling with clinic.js**:

**Template:** `templates/clinic-js-profiling.sh` - clinic.js doctor, flame, bubbleprof, and heapprofile commands

**Node.js built-in profiling**:

**Template:** `templates/node-builtin-profiling.sh` - V8 CPU profiler, trace events, and event loop delay monitoring commands

**Chrome DevTools protocol profiling**:

**Template:** `templates/chrome-devtools-profiling.sh` - Node.js inspector startup and programmatic CPU profiling via Chrome DevTools Protocol

**React Profiler API**:

**Template:** `templates/react-profiler.jsx` - React Profiler component wrapper with onRender callback logging render timing
```bash
# React DevTools Profiler: enable "Record why each component rendered"
# in React DevTools settings → Profiler tab → click record → interact → stop
# Examine flame chart for wasted renders (components that rendered with same output)
```

**Python profiling**:

**Template:** `templates/python-profiling.sh` - cProfile, line_profiler, py-spy, and scalene commands for Python performance analysis

**Go benchmark testing and profiling**:

**Template:** `templates/go-benchmark-profiling.sh` - Go benchmark, CPU/memory profiling, trace execution, and live server profiling commands

---

## Step 3: Optimize
- Apply optimizations with clear **before/after** comparisons
- Prioritize by impact matrix: **high-impact + low-effort first**
- Never sacrifice readability for marginal gains
- Run tests after each optimization to ensure no regressions
- For database changes, test with production-like data volumes - small test datasets hide performance problems
- For frontend changes, test on low-end devices and throttled connections

## Step 4: Measure and Report

**Template:** `templates/optimization-report.md` - Performance optimization report template with changes table, metrics, tradeoffs, and follow-up recommendations

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `area`: "frontend" | "backend" | "database" | "bundle" | "memory" | "concurrency" | "network" | "rendering" | "build" | "runtime" | "observability" | "all" - default focus area
- `bundleSizeTarget`: number - target bundle size in KB
- `buildTimeTarget`: number - target build time in seconds
- `lcpTarget`: number - target LCP in milliseconds (default: 2500)
- `inpTarget`: number - target INP in milliseconds (default: 200)
- `clsTarget`: number - target CLS score (default: 0.1)
- `autoApply`: boolean - apply optimizations automatically (default: true)
- `ignorePaths`: string[] - paths to skip in analysis
- `stackProfile`: "node" | "python" | "go" | "mixed" - which profiling tools and patterns to prioritize
