---
name: genskills:debug
description: >
  Debug issues systematically - trace errors, analyze stack traces,
  identify root causes. Triggers on: "debug", "why is this failing",
  "trace this error", "find the bug", "investigate", "troubleshoot".
user-invocable: true
argument-hint: "[error message or file:line]"
allowed-tools: "Read, Edit, Grep, Glob, Bash(git log*), Bash(git blame*), Bash(git diff*), Bash(git bisect*), Bash(node *), Bash(python *), Bash(npm run*), Bash(npm test*), Bash(npx *), Bash(go *), Bash(curl *), Bash(netstat *), Bash(ss *), Bash(lsof *)"
genskills-version: "1.4.2"
genskills-category: "development"
genskills-depends: []
---

# Debug

A senior engineer's systematic playbook for finding and fixing root causes - from trivial typos to distributed system failures.

## Core Principles

Before touching anything, internalize these:

1. **Observe before you hypothesize.** Collect evidence first. Premature theories cause tunnel vision.
2. **Change one thing at a time.** Multiple simultaneous changes make it impossible to attribute causality.
3. **The bug is in your code.** Until proven otherwise, assume the defect is yours - not the compiler, not the OS, not the hardware.
4. **Reproduce before you fix.** A fix without a reproduction is a guess. A guess that passes CI is still a guess.
5. **Production is sacred.** When debugging production, you are a read-only investigator. No cowboy fixes.

---

## Process

### Step 0: Load Project Context

- Check for `CLAUDE.md` at the project root - it may document known issues, architecture decisions, or debugging tips
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Identify the runtime environment: language, framework, deployment target (serverless, container, bare metal)
- Note the error monitoring stack if any (Sentry, Datadog, CloudWatch, etc.)

### Step 1: Understand the Problem

- If `$ARGUMENTS` contains an error message, parse it for:
  - **Error type/code**: e.g., TypeError, ENOENT, 404, TS2345, SIGABRT, OOMKilled, ENOMEM
  - **Stack trace**: extract file paths, line numbers, function names - read bottom-up for the origination point
  - **Context clues**: when does it happen? Under what load? After how long? Is it deterministic?
  - **Error frequency**: one-off vs. recurring vs. escalating (memory leaks often show escalating patterns)
- If `$ARGUMENTS` contains file:line, read that location and surrounding context (50 lines in each direction)
- If no arguments, ask the user to describe the issue or paste the error
- **Classify the bug early**: crash, incorrect behavior, performance degradation, data corruption, intermittent failure - each class demands a different investigation strategy

### Step 2: Reproduce

Reproduction is the single most important step. Without it, you are debugging in the dark.

- **Deterministic bugs**: Run the relevant command (`npm test`, `npm run dev`, `go test ./...`, `pytest`, etc.) and confirm the failure
- **Intermittent bugs**: Look for timing dependencies, race conditions, resource exhaustion - try running under load or with constrained resources
- **Environment-specific bugs**: Compare environment variables, OS version, dependency versions, locale settings, timezone, available memory
- **Data-dependent bugs**: Identify the specific input that triggers the failure; minimize it to the smallest reproducing case
- **Production-only bugs**: If you cannot reproduce locally, instrument with structured logging and feature flags to narrow the blast radius (see Production Debugging below)

If you can reproduce it, you are 60% done.

### Step 3: Trace the Error

Follow the execution path systematically. Work from the symptom back toward the cause.

#### 3a: Static Trace (Code Reading)

1. Read the file where the error occurs - understand the full function, not just the failing line
2. Trace the call stack upward - `Grep` for function callers across the codebase
3. Check the inputs: what data flows into this function? Are types and values as expected?
4. Check imported modules and their versions - has an API surface changed?
5. Look for implicit dependencies: global state, singletons, environment variables, file system assumptions

#### 3b: History Trace (Git Archaeology)

1. `git log --oneline -20 -- <file>` - did a recent change introduce this?
2. `git blame -L <start>,<end> <file>` - who wrote this line, when, and in what commit?
3. `git diff HEAD~5 -- <file>` - are recent changes the culprit?
4. `git log --all --oneline --grep="<error keyword>"` - has this error been encountered before?

#### 3c: Binary Search with git bisect

When you know a regression exists but not which commit introduced it:

**Template:** `templates/git-bisect-workflow.sh`
Interactive git bisect workflow: mark commits as good/bad to binary-search for the regression.

Automate it when a test command exists:
```bash
git bisect start HEAD <known-good-commit>
git bisect run npm test
```

This finds the offending commit in O(log n) steps. Invaluable for regressions in large histories.

#### 3d: Runtime Trace (Dynamic Analysis)

When static analysis is insufficient, use runtime tools:

**Node.js:**
- `node --inspect <script>` - attach Chrome DevTools debugger
- `node --inspect-brk <script>` - break on first line
- `npx clinic doctor -- node <script>` - auto-detect common performance issues
- `npx clinic flame -- node <script>` - generate flame graph
- `npx clinic bubbleprof -- node <script>` - analyze async operations
- `npx why-is-node-running` - detect what handles are keeping the process alive

**Python:**
- `python -m pdb <script>` - interactive debugger
- `python -m tracemalloc` - trace memory allocations (enable with `tracemalloc.start()`)
- `python -c "import faulthandler; faulthandler.enable()"` - dump traceback on SIGSEGV/SIGABRT
- `py-spy top --pid <pid>` - live top-like view of Python process
- `py-spy record -o profile.svg --pid <pid>` - flame graph for running process

**Go:**
- `dlv debug <package>` - Delve interactive debugger
- `go test -race ./...` - race condition detector (always run this)
- `go tool pprof http://localhost:6060/debug/pprof/heap` - heap profiling
- `go tool pprof http://localhost:6060/debug/pprof/profile?seconds=30` - CPU profiling
- `go tool trace trace.out` - execution tracer for goroutine analysis
- `GODEBUG=gctrace=1 go run .` - GC diagnostics

### Step 4: Identify Root Cause

#### Common Root Cause Categories

**Data & Type Errors:**
- **Null/undefined access**: Missing null checks, optional chaining needed, API returned unexpected shape
- **Type mismatch**: Wrong data shape, missing fields, API response changed, implicit coercion
- **Serialization errors**: JSON.parse on non-JSON, circular references in JSON.stringify, BigInt serialization, Date objects losing timezone through serialization boundary
- **Encoding issues**: UTF-8 BOM in files, mixed encodings in database, emoji/surrogate pair handling, path encoding on Windows vs. Unix
- **Floating point precision**: `0.1 + 0.2 !== 0.3`, currency math without integer cents, comparing floats with `===`

**State & Timing Errors:**
- **State issue**: Stale state, missing update, wrong initialization order, closure capturing old value
- **Async issue**: Race condition, missing `await`, unhandled rejection, callback fired multiple times
- **Event loop blocking**: Synchronous file I/O, CPU-heavy computation on main thread, `JSON.parse` on huge payloads
- **Race conditions**: Two processes writing the same resource, read-modify-write without a lock, optimistic concurrency violation
- **Deadlocks**: Circular lock acquisition order, database row locks in conflicting order, `Promise.all` with interdependent promises
- **Thread safety**: Shared mutable state without synchronization, non-atomic read-modify-write, unsafe concurrent map access in Go

**Environment & Configuration Errors:**
- **Environment**: Missing env var, wrong config, version mismatch, platform difference (Windows paths vs. POSIX)
- **Timezone bugs**: Server in UTC, client in local time, daylight saving transitions, `new Date()` behavior varies by locale
- **DNS resolution failures**: Wrong `/etc/resolv.conf`, DNS cache poisoning, split-horizon DNS returning internal IPs externally
- **SSL/TLS issues**: Expired certificate, self-signed cert in chain, TLS version mismatch, SNI misconfiguration, clock skew breaking certificate validation

**Dependency & Module Errors:**
- **Dependency issue**: Breaking change in updated package, version conflict, missing peer dep, phantom dependencies in hoisted node_modules
- **Import/module issue**: Circular dependency, wrong import path, missing export, ESM vs. CJS interop
- **Memory leaks**: Unbounded caches, event listeners never removed, closures holding references, orphaned timers/intervals, growing WeakRef-unaware collections

**Infrastructure Errors:**
- **Connection pool exhaustion**: Database connections not returned, HTTP agents holding sockets, connection limits hit under load
- **Resource limits**: File descriptor limits (ulimit -n), process limits, memory limits (OOMKilled in containers), disk space
- **Network partitions**: Timeout vs. connection refused vs. connection reset - each tells a different story

#### Framework-Specific Debugging

**React:**
- Use React DevTools Profiler to find unnecessary re-renders
- `npx why-did-you-render` - patches React to log avoidable re-renders
- Check for missing `key` props causing full subtree remounts
- Stale closure in `useEffect` - dependency array is missing a value
- State updates on unmounted components - use cleanup functions or AbortController
- Context causing cascading re-renders - split contexts by update frequency

**Next.js:**
- **Server vs. Client boundary bugs**: `"use client"` directive missing, trying to use `window` in server component, hydration mismatch
- **RSC debugging**: Server components cannot use hooks or browser APIs - check the component tree boundary
- **Hydration mismatches**: Server HTML differs from client render - common with dates, random values, user-agent-dependent rendering. Check `suppressHydrationWarning` only as last resort.
- **API routes**: Check `req.body` parsing, middleware ordering, edge runtime limitations
- `NEXT_DEBUG=1 next dev` - verbose logging
- `next build` output shows static vs. dynamic routes - unexpected dynamic routes indicate missing `generateStaticParams`

**Node.js (Server):**
- `node --inspect` + Chrome DevTools for breakpoints, heap snapshots, CPU profiles
- `node --max-old-space-size=4096` - increase heap if OOM, but investigate the leak first
- `process.memoryUsage()` - quick check for memory growth over time
- Event loop lag: `perf_hooks.monitorEventLoopDelay()` or `npx clinic doctor`
- Unhandled rejections: `process.on('unhandledRejection', ...)` - find the missing `.catch()`

**Python:**
- `python -m pdb` for interactive stepping; `breakpoint()` in code (Python 3.7+)
- `tracemalloc.start(); ... ; snapshot = tracemalloc.take_snapshot()` - memory allocation tracing
- `objgraph.show_most_common_types()` - find what objects are accumulating
- `asyncio.get_event_loop().set_debug(True)` - verbose async debugging
- `python -Werror` - turn warnings into errors to catch deprecation issues early

**Go:**
- `go test -race ./...` - non-negotiable. Run this on every test suite. Data races are undefined behavior.
- `go vet ./...` - catches common mistakes the compiler misses
- Goroutine leaks: `runtime.NumGoroutine()` should stabilize, not grow. `pprof` goroutine profile shows stuck goroutines.
- Channel deadlocks: sending to a full unbuffered channel with no receiver, or selecting without a default case
- `GOTRACEBACK=all` - full goroutine dump on panic

### Step 5: Advanced Debugging Techniques

#### Memory Leak Detection

1. **Identify the symptom**: Process RSS growing over time, OOMKilled in container, GC pauses increasing
2. **Take heap snapshots** at intervals:
   - Node.js: Chrome DevTools > Memory > Take Heap Snapshot (compare two snapshots with "Comparison" view)
   - Python: `tracemalloc.take_snapshot()` and compare with `snapshot.compare_to(old, 'lineno')`
   - Go: `go tool pprof -diff_base=heap1.prof heap2.prof`
3. **Look for**: Objects whose count grows linearly with time/requests - that is the leak
4. **Common culprits**: Global caches without eviction, event emitters with listeners added per-request, closures capturing large scopes, timers/intervals never cleared

#### Performance Debugging

**Flame Graphs** - visualize where CPU time is spent:
- Node.js: `npx clinic flame -- node server.js` or `node --prof` then `node --prof-process`
- Python: `py-spy record -o flame.svg --pid <pid>`
- Go: `go tool pprof -http=:8080 cpu.prof`
- Look for wide plateaus (functions that dominate) and tall stacks (deep call chains)

**Heap Snapshots** - visualize memory allocation:
- Take two snapshots, compare. Growing object types are the leak.
- Sort by "retained size" not "shallow size" - a small object can retain a huge graph.

**Event Loop Utilization (Node.js):**
- `perf_hooks.performance.eventLoopUtilization()` - ratio of busy to idle
- If utilization > 0.8, the event loop is saturated. Move CPU work to worker threads.
- Long tasks block timers and I/O callbacks - profile to find them.

#### Network Debugging

**Request Waterfall Analysis:**
- Total time = DNS + TCP + TLS + TTFB + Transfer
- Slow DNS: Check resolver configuration, consider DNS caching
- Slow TLS: Check certificate chain length, enable session resumption
- Slow TTFB: Backend is slow - profile the server
- Slow Transfer: Large payload - enable compression, paginate

**Specific Network Issues:**
- **CORS**: Check `Access-Control-Allow-Origin`, `Access-Control-Allow-Methods`, `Access-Control-Allow-Headers`. Preflight OPTIONS request must return 200.
- **WebSocket debugging**: Check upgrade handshake, ping/pong frames for keepalive, close frame reason codes
- **Connection resets**: Server-side timeout, load balancer idle timeout, firewall dropping long-lived connections
- `curl -v <url>` - shows full request/response headers, TLS handshake, timing
- `curl -w "@curl-format.txt" -o /dev/null -s <url>` - custom timing output (DNS, connect, TLS, TTFB)

#### Database Debugging

**Slow Query Analysis:**
- Enable slow query log: `SET GLOBAL slow_query_log = 'ON';` (MySQL) or `log_min_duration_statement = 1000` (PostgreSQL)
- `EXPLAIN ANALYZE <query>` - actual execution plan with row counts and timing
- Look for: sequential scans on large tables, missing indexes, bad join order, N+1 query patterns

**Connection Pool Exhaustion:**
- Symptom: requests hang, then timeout with "cannot acquire connection"
- Diagnosis: check pool size vs. concurrent requests. Each `await db.query()` holds a connection.
- Fix: ensure connections are always released (use `try/finally`), reduce pool checkout timeout to fail fast, increase pool size cautiously

**Database Deadlocks:**
- `SHOW ENGINE INNODB STATUS\G` (MySQL) - shows last detected deadlock
- `SELECT * FROM pg_locks WHERE NOT granted;` (PostgreSQL) - show blocked locks
- Fix: ensure consistent lock ordering, reduce transaction scope, use `SELECT ... FOR UPDATE NOWAIT`

#### Log Analysis Patterns

**Structured Log Parsing:**
- Filter by severity: `grep '"level":"error"'` or `jq 'select(.level == "error")'`
- Filter by time window: `jq 'select(.timestamp >= "2024-01-15T10:00:00")'`
- Filter by request ID: trace a single request through all services

**Correlation IDs:**
- Every request should carry a unique ID through all service boundaries
- Grep for the correlation ID across all service logs to reconstruct the full request lifecycle
- Missing correlation ID at a boundary? That is where the request was dropped or transformed incorrectly.

**Distributed Trace Analysis:**
- Identify the span with the highest self-time - that is the bottleneck
- Look for gaps between spans - network latency, queue wait time, or missing instrumentation
- Fan-out patterns: if a request triggers 100 downstream calls, that is the problem regardless of individual span duration

### Step 6: Fix

- Apply the **minimal fix** that addresses the root cause - do not refactor while debugging
- Add error handling if the error surface was unprotected
- Verify the fix resolves the issue: re-run the failing command
- If tests exist, run them to ensure no regressions
- If the fix is in a hot path, consider performance implications
- If the fix changes behavior, check for downstream consumers that may depend on the old (broken) behavior

### Step 7: Explain, Prevent, and Harden

**Template:** `templates/debug-report.md`
Structured debug report covering problem, investigation, root cause, fix, verification, and prevention.

---

## Production Debugging Mindset

When the bug is in production, the rules change:

1. **Read-only investigation.** Do not modify production state. Do not run migrations. Do not restart services unless you understand why.
2. **Assess blast radius first.** How many users are affected? Is the error rate growing? Is data being corrupted, or just requests failing?
3. **Use feature flags for isolation.** If you suspect a specific feature, disable it with a flag. This is faster and safer than a rollback.
4. **Shadow testing.** Replay production traffic against a fixed version in a staging environment to validate the fix before deploying.
5. **Correlate with deploys.** `git log --oneline --since="2 hours ago"` - did anything deploy recently? Most production bugs are caused by recent changes.
6. **Check the usual suspects**: Did a dependency update? Did a certificate expire? Did a third-party API change its contract? Did the infrastructure provider have an incident?
7. **Preserve evidence.** Take heap dumps, capture thread states, save log windows BEFORE restarting. A restart destroys the crime scene.
8. **Communicate.** If the issue affects users, update the status page. Silence is worse than a known outage.

---

## Configuration

Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `autoFix`: boolean - apply fix automatically or just report (default: true)
- `runTests`: boolean - run tests after fix to verify (default: true)
- `verbosity`: "minimal" | "detailed" - how much to explain (default: "detailed")
- `bisectEnabled`: boolean - use git bisect for regression hunting (default: false)
- `productionMode`: boolean - enforce read-only investigation, no auto-fix (default: false)
