---
name: genskills:error-boundary
description: >
  Analyze codebase for unhandled error surfaces - missing catch blocks,
  unhandled promise rejections, missing React error boundaries, uncaught
  async exceptions. Triggers on: "find unhandled errors", "error coverage",
  "error boundaries", "unhandled exceptions", "missing error handling".
user-invocable: true
argument-hint: "[file or directory] [--fix] [--severity critical|high|medium|low]"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(npm test*), Bash(npm run*), Bash(npx *), Bash(git diff*)"
genskills-version: "1.3.0"
genskills-category: "code-quality"
genskills-depends: []
---

# Error Boundary Analysis

Find and fix unhandled error surfaces across the codebase.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any error handling conventions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Identify the framework to know which error patterns to check (React, Next.js, Remix, SvelteKit, Nuxt, Astro, Express, Fastify, Hono, NestJS, FastAPI, Django, etc.)

### Step 1: Parse Arguments
Parse `$ARGUMENTS`:
- First positional: file or directory to analyze
- `--fix`: automatically apply fixes for critical and high severity issues
- `--severity`: minimum severity to report - "critical" | "high" | "medium" | "low" (default: "low")
- `--changed`: only analyze recently changed files (`git diff --name-only HEAD~5`)

If no arguments, scan `src/` or project root.
Prioritize: API routes → data-fetching → UI components → utilities.

### Step 2: Detect Error Surfaces by Category

**Unhandled Promises:**
- `async` functions without try/catch wrapping their await calls
- `.then()` chains without `.catch()` or final error handler
- `await` calls not wrapped in try/catch (especially in route handlers)
- Promise constructors without reject handling
- `Promise.all` without error handling (one rejection loses all results - suggest `Promise.allSettled`)
- `Promise.race` without timeout/rejection handling
- Missing `unhandledRejection` process handler in Node.js entry points
- Missing `uncaughtException` handler in Node.js entry points
- Floating promises (async calls without await or `.catch()`)

**Missing React/Framework Error Boundaries:**
- Check if any ErrorBoundary component exists in the project
- Route-level components without error boundary wrapping
- `useEffect` with async operations lacking error handling
- Data-fetching hooks/components without error states (loading/error/data pattern)
- Suspense boundaries without fallback error handling
- React Server Components without error boundaries at the server/client boundary
- **Next.js App Router**: Check for `error.tsx` and `global-error.tsx` in each route segment
- **Next.js Pages**: Check for custom `_error.tsx` and `500.tsx`
- **Remix**: Check for `ErrorBoundary` exports in route modules
- **SvelteKit**: Check for `+error.svelte` files in route directories, `handleError` hook in `hooks.server.ts`
- **Nuxt**: Check for `error.vue` and `NuxtErrorBoundary` usage
- **Astro**: Check for error handling in API routes and middleware

**API Route Handlers:**
- Express/Fastify/Hono/NestJS route handlers without try/catch
- Error responses returning 200 status for errors (should be 4xx/5xx)
- Unvalidated request body/params/query usage
- Missing global error middleware:
  - Express: `app.use((err, req, res, next) => ...)`
  - Fastify: `setErrorHandler`
  - Hono: `app.onError`
  - NestJS: `ExceptionFilter`
- Missing input validation (zod, joi, class-validator, typebox)
- Missing async error forwarding in Express (no `next(err)` in catch blocks)
- Streaming responses without error handling mid-stream

**Database Operations:**
- Database calls without try/catch (Prisma, Drizzle, Sequelize, TypeORM, Knex, raw SQL)
- Transaction error handling missing rollback
- Connection pool exhaustion not handled (missing timeout/retry)
- Missing `.catch()` on query builders
- Unique constraint violations not caught (duplicate key errors)
- Migration failures without rollback strategy

**File System / External Calls:**
- `fs` operations without error handling (especially `fs.readFile`, `fs.writeFile`, `fs.unlink`)
- HTTP client calls (`fetch`, `axios`, `got`, `ky`) without catch
- Missing timeout on external HTTP calls
- `child_process`/`exec`/`spawn` calls without error handling
- Stream operations without error event listeners (`stream.on('error', ...)`)
- WebSocket connections without error/close handling
- gRPC calls without deadline/timeout

**Third-Party Integrations:**
- Payment provider calls (Stripe, PayPal) without error handling
- Email/SMS service calls without retry/fallback
- Cloud storage operations (S3, GCS) without error handling
- Queue/message broker operations without dead letter handling
- Cache operations (Redis) without fallback to source

### Step 3: Classify Severity

| Severity | Meaning | Example |
|---|---|---|
| **Critical** | Process crash, data corruption, broken state | Unhandled DB error in write path, no global error handler |
| **High** | User-facing raw errors, degraded UX | Missing error boundary on dashboard, no API error response |
| **Medium** | Silent failures, lost data, poor observability | Swallowed fetch errors, empty catch blocks, missing logging |
| **Low** | Edge cases, unlikely failure modes | fs.stat without catch, optional feature without fallback |

### Step 4: Generate Report
```
## Error Boundary Report

### Critical - Process Crash / Data Loss Risk
- [file:line] `await db.query()` in route handler without try/catch
  → Wrap in try/catch, return 500 response with generic message
- [file:line] No global error handler in Express app
  → Add `app.use((err, req, res, next) => ...)` error middleware

### High - User-Facing Error Gaps
- [file:line] No ErrorBoundary around <Dashboard /> route
  → Add ErrorBoundary with fallback UI
- [file:line] Missing error.tsx in app/dashboard/
  → Create error.tsx with user-friendly error UI
- [file:line] API route returns 200 on database error
  → Return appropriate 500 status with error message

### Medium - Silent Failures
- [file:line] fetch() in useEffect without .catch()
  → Add error state and catch handler
- [file:line] Empty catch block swallows error
  → Log error or re-throw, don't silently swallow
- [file:line] Promise.all with 5 promises - one failure loses all
  → Consider Promise.allSettled for partial success handling

### Low - Edge Cases
- [file:line] fs.readFile on config without error callback
  → Add error handling for missing file case

### Error Handling Coverage Summary
| Layer | Covered | Missing | Status |
|---|---|---|---|
| Global error handler | ✓ | - | ✅ |
| Route-level boundaries | 8/12 | 4 routes | ⚠️ |
| API error responses | 15/20 | 5 handlers | ⚠️ |
| Database operations | 10/14 | 4 queries | ❌ |
| External API calls | 3/8 | 5 calls | ❌ |

### Summary
- X critical, Y high, Z medium, W low issues found
- Error handling coverage: ~N%
- Estimated effort: N critical (quick fix), N high (moderate), N medium (low priority)

### Follow-up
- Run `/genskills:test-generator` to add tests for error paths
- Run `/genskills:security-audit` to check if error messages leak sensitive info
```

### Step 5: Auto-fix (if --fix)
If `--fix` flag is set, apply fixes for critical and high severity:
- Wrap unwrapped async route handlers in try/catch with proper error response
- Add missing global error middleware
- Create missing `error.tsx`/`error.vue` files with basic error UI
- Add `.catch()` to unhandled promise chains
- Replace empty catch blocks with error logging
- Replace `Promise.all` with `Promise.allSettled` where appropriate

**Do NOT auto-fix:**
- Complex error recovery logic (requires business context)
- Error boundary component design (requires UX decisions)
- Transaction rollback strategies (requires domain knowledge)
- Retry/circuit-breaker patterns (requires architecture decisions)

After fixes, re-run analysis to verify improvements.

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `framework`: string - override auto-detected framework
- `autoFix`: boolean - automatically apply fixes for critical issues (default: false)
- `ignorePaths`: string[] - paths to skip
- `minSeverity`: "low" | "medium" | "high" | "critical" - minimum severity to report
- `checkThirdParty`: boolean - include third-party integration checks (default: true)
- `requireGlobalHandler`: boolean - flag missing global error handler as critical (default: true)
