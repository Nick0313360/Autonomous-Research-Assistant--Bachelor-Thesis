---
name: genskills:api-client-gen
description: >
  Generate typed API clients/SDKs from OpenAPI specs, GraphQL schemas, or existing endpoints.
  Triggers on: "generate client", "api client", "sdk gen", "typed client",
  "openapi client", "graphql codegen".
user-invocable: true
argument-hint: "[source] [output] - e.g., 'openapi.yaml ./src/api' or 'http://localhost:3000/api'"
allowed-tools: "Read, Write, Edit, Grep, Glob, WebFetch, Bash(npm *), Bash(npx *), Bash(pip *), Bash(curl *)"
genskills-version: "1.4.2"
genskills-category: "development"
genskills-depends: []
---

# API Client Gen

Generate production-grade, fully typed API clients from OpenAPI specs, GraphQL schemas, tRPC routers, or live endpoints. The generated client includes advanced type patterns, framework integrations, authentication flows, middleware pipelines, real-time support, testing utilities, and SDK distribution scaffolding.

## Process

### Step 0: Load Context

- Read `CLAUDE.md` for API conventions, preferred HTTP libraries, auth patterns, and environment configuration
- Read `${CLAUDE_SKILL_DIR}/_config.json` for saved preferences and prior generation history
- Scan `package.json` / `pyproject.toml` / `go.mod` for existing dependencies that inform generation choices
- Detect monorepo structure (workspaces, packages) to determine correct output location

### Step 1: Detect Source

Parse `$ARGUMENTS` to identify the API source:

1. **OpenAPI/Swagger file** - local `.yaml`/`.json` file (v2 or v3.x)
2. **OpenAPI URL** - remote spec URL (fetch and cache locally)
3. **GraphQL schema** - `.graphql`/`.gql` file or introspection endpoint
4. **GraphQL endpoint** - run introspection query against a live server
5. **tRPC router** - TypeScript router definition file (extract procedure types via static analysis)
6. **Live REST API** - base URL to reverse-engineer from route files, Swagger UI, or HAR captures
7. **Postman/Insomnia collection** - import from exported collection JSON

If no source provided, search the project for:
- `openapi.yaml`, `openapi.json`, `swagger.yaml`, `swagger.json` in root and `docs/` directories
- `schema.graphql`, `schema.gql` in root and `src/` directories
- `*.trpc.ts`, `trpc/router.ts`, `server/routers/*.ts` for tRPC definitions
- API route files (`pages/api/**`, `app/api/**`, `routes/**`) to extract endpoints manually
- `.har` files or Postman exports in project root

### Step 2: Detect Target Stack

- Identify the project language (TypeScript, Python, Go, Rust, etc.)
- Detect existing HTTP libraries (fetch, axios, ky, got, ofetch, httpx, reqwest, net/http)
- Check for framework context: Next.js, Nuxt, SvelteKit, Remix, FastAPI, Gin, Actix
- Detect state management / data fetching libraries: TanStack Query, SWR, Apollo, urql, Relay
- Check for existing generated clients to understand the preferred pattern and avoid conflicts
- Detect runtime: Node.js, Deno, Bun, browser-only, edge runtime (affects available APIs)
- Check `tsconfig.json` for `strict`, `exactOptionalPropertyTypes`, `noUncheckedIndexedAccess` to calibrate type strictness

### Step 3: Parse API Spec

Extract from the spec or route files:

- All endpoints: method, path, parameters (path, query, body, header, cookie)
- Request/response types with full schemas including nested objects, arrays, enums, and discriminated unions
- Authentication methods (Bearer, API key, OAuth2, cookie/session, mTLS, AWS SigV4)
- Base URL and server configuration (multiple environments: dev, staging, production)
- Error response shapes per endpoint and per status code range
- Rate limiting headers and policies (`X-RateLimit-*`, `Retry-After`)
- Pagination strategy (cursor-based, offset-based, keyset, link-header)
- Deprecation notices and sunset headers
- Content types (JSON, multipart/form-data, application/x-www-form-urlencoded, octet-stream)
- WebSocket or SSE endpoints for real-time capabilities
- Webhook definitions and payload schemas

### Step 4: Generate Types

**For TypeScript projects, generate advanced type patterns:**

**Template:** `templates/branded-types.ts`
Branded ID types, discriminated union responses, pagination wrappers, conditional relation types, query builder interface, and per-endpoint error types

**For Python projects:**

**Template:** `templates/pydantic-types.py`
Pydantic models with NewType IDs, generic pagination, and discriminated union API responses

### Step 5: Generate Client Core

**File structure:**

```
src/api/
  client.ts              - Base client class with interceptor pipeline
  types.ts               - All request/response types (branded, discriminated, conditional)
  errors.ts              - Typed error hierarchy and discrimination utilities
  auth.ts                - Authentication flows and token management
  middleware.ts           - Request/response middleware pipeline
  pagination.ts          - Generic pagination helpers and iterators
  cache.ts               - Response caching (SWR pattern)
  retry.ts               - Retry strategies and circuit breaker
  realtime.ts            - WebSocket, SSE, and long-polling clients
  endpoints/
    users.ts             - Per-resource methods with full types
    posts.ts
    organizations.ts
    ...
  hooks/                 - React Query / TanStack Query hooks (if applicable)
    useUsers.ts
    usePosts.ts
    queryKeys.ts         - Query key factory
    prefetch.ts          - Server-side prefetch utilities
    optimistic.ts        - Optimistic update helpers
  testing/
    handlers.ts          - MSW request handlers
    fixtures.ts          - Typed fixture factories
    recorder.ts          - Request recording/playback
  index.ts               - Barrel export with tree-shakeable named exports
  package.json           - (optional) For SDK distribution as a standalone package
```

**Base client with middleware pipeline:**

**Template:** `templates/base-client.ts`
ApiClient class with middleware pipeline, resource namespaces, and Middleware type definition

### Step 6: Error Handling

Generate a comprehensive error handling system that discriminates error types and applies appropriate recovery strategies.

**Typed error hierarchy:**

**Template:** `templates/error-hierarchy.ts`
Discriminated error subclasses (Network, Auth, Validation, RateLimit, Server) with type guards and pattern-matching utility

**Retry strategies per error type:**

**Template:** `templates/retry-strategy.ts`
RetryStrategy interface with exponential backoff, error-type-aware retry logic, and CircuitBreaker class

**Per-endpoint timeout configuration:**

```typescript
// Endpoint-level timeout overrides
const endpoints = {
  "users.list":       { timeout: 5000 },
  "reports.generate": { timeout: 60000 },  // long-running report
  "health.check":     { timeout: 2000 },
} satisfies Record<string, { timeout: number }>;
```

### Step 7: Authentication Flows

Generate authentication infrastructure appropriate to the detected auth methods.

**Token refresh interceptor with request queuing:**

**Template:** `templates/auth-providers.ts`
Token refresh with request queuing, OAuth2 PKCE, rotating API keys, session/CSRF auth, and multi-tenant header injection

### Step 8: Request/Response Middleware

**Request signing (AWS SigV4, HMAC):**

**Template:** `templates/signing-middleware.ts`
AWS SigV4 request signing middleware and HMAC signing middleware with timestamp headers

**Request deduplication:**

**Template:** `templates/dedup-middleware.ts`
Request deduplication middleware that coalesces concurrent identical GET requests

**Response caching (SWR pattern):**

**Template:** `templates/swr-cache.ts`
SWR (stale-while-revalidate) response cache with configurable max age and background revalidation

**Request/response logging with PII redaction:**

**Template:** `templates/logging-middleware.ts`
Request/response logging middleware with configurable PII redaction for headers and body fields

**Compression negotiation:**

**Template:** `templates/compression-middleware.ts`
Compression negotiation middleware supporting gzip, Brotli, and deflate encoding

### Step 9: React Query / TanStack Query Integration

If the project uses React (or Vue/Solid/Svelte with TanStack Query), generate a full hooks layer.

**Query key factory:**

**Template:** `templates/query-keys.ts`
Hierarchical query key factory for TanStack Query with per-resource key builders

**Generated hooks - useQuery, useMutation, useInfiniteQuery:**

**Template:** `templates/tanstack-query-hooks.ts`
Generated React hooks: useQuery, useSuspenseQuery, useInfiniteQuery, useMutation with optimistic updates and cache rollback

**Prefetch utilities for SSR / route loaders:**

**Template:** `templates/prefetch-utils.ts`
SSR prefetch utilities with QueryClient dehydration for Next.js App Router

**Cache invalidation patterns:**

**Template:** `templates/invalidation-rules.ts`
Declarative cache invalidation rules mapping mutation endpoints to query key invalidations

### Step 10: tRPC Client Generation

If the source is a tRPC router, generate a fully typed caller layer.

**Template:** `templates/trpc-client.ts`
Batched HTTP + WebSocket tRPC client, server-side caller, React hooks, and typed subscription helper

### Step 11: GraphQL Advanced Generation

**Fragment colocation:**

**Template:** `templates/graphql-fragments.ts`
Colocated GraphQL fragments for User fields and User-with-Posts relation

**Persisted queries:**

**Template:** `templates/persisted-queries.ts`
Pre-hashed persisted query map and Apollo Link for automatic hash injection

**Automatic query complexity calculation:**

**Template:** `templates/query-complexity.ts`
Client-side query complexity calculator that estimates cost before sending to avoid server rejection

**Subscription client with reconnection:**

**Template:** `templates/graphql-subscriptions.ts`
GraphQL WebSocket subscription client with exponential backoff reconnection

**Normalized cache helpers:**

**Template:** `templates/graphql-cache.ts`
Apollo InMemoryCache with type policies, relay/offset pagination merging, and optimistic update helpers

### Step 12: Real-Time API Clients

Generate clients for WebSocket, SSE, and long-polling endpoints discovered in the spec.

**WebSocket client with typed events:**

**Template:** `templates/websocket-client.ts`
Typed WebSocket client with discriminated event union, heartbeat, auto-reconnect with backoff, and unsubscribe support

**Server-Sent Events (SSE) helper:**

**Template:** `templates/sse-client.ts`
Generic SSE client with typed event subscriptions, AbortSignal support, and long-polling fallback

### Step 13: Testing Utilities

**MSW (Mock Service Worker) handler generation from spec:**

**Template:** `templates/msw-handlers.ts`
MSW request handlers auto-generated from OpenAPI spec with CRUD operations and error scenario overrides

**Fixture generation from response schemas:**

**Template:** `templates/fixture-factories.ts`
Type-safe fixture factories using Faker.js with build/buildList helpers and paginated list generators

**Contract testing setup (Pact):**

**Template:** `templates/contract-tests.ts`
Pact V4 consumer-driven contract test scaffolding for API endpoint verification

**Request recording/playback:**

**Template:** `templates/request-recorder.ts`
Request recording/playback interceptor for deterministic test replay with file serialization

### Step 14: SDK Distribution Patterns

When the user wants to distribute the generated client as a standalone package:

**Package structure:**

```
packages/api-client/
  package.json            - name, version, exports map, peerDependencies
  tsconfig.json           - strict, declaration, declarationMap
  tsup.config.ts          - build config (ESM + CJS dual format)
  src/
    index.ts              - main entry (tree-shakeable named exports)
    client.ts
    types.ts
    errors.ts
    resources/
      users.ts
      posts.ts
    react/
      index.ts            - separate entry point: "my-api/react"
      hooks.ts
      queryKeys.ts
  CHANGELOG.md
```

**package.json with proper exports map:**

**Template:** `templates/sdk-package.json`
Package.json with dual ESM/CJS exports map, sub-path exports for react and testing, and optional peer dependencies

**Versioning strategy aligned with API versions:**

**Template:** `templates/version-middleware.ts`
Version header middleware that injects client and API version headers for server-side compatibility checks

### Step 15: Validate

- **Type-check** the generated code with `tsc --noEmit` (or the project's type-check command)
- **Verify coverage**: confirm every endpoint in the spec has a corresponding method in the client
- **Check imports**: ensure all imports resolve correctly, no circular dependencies
- **Lint**: run the project's linter on generated files to ensure code style conformance
- **Verify tree-shaking**: ensure no side effects at module level that would prevent dead code elimination
- **Test smoke**: if test utilities were generated, run a basic sanity check (fixture builds, MSW handlers compile)

### Step 16: Report

```
## API Client Generated

### Source: <spec-file-or-url>
### Output: <output-directory>

### Generated
- <N> endpoint methods across <M> resources
- <N> request/response types (with branded IDs, discriminated unions, conditional relations)
- Base client with <auth-method> authentication
- Error hierarchy: NetworkError, AuthenticationError, ValidationError, RateLimitError, ServerError
- Middleware pipeline: [auth, signing, dedup, cache, retry, circuit-breaker, logging]
- React Query hooks with optimistic updates, infinite scroll, prefetch, and query key factory
- Real-time: WebSocket client with typed events / SSE client / long-polling fallback
- Testing: MSW handlers, fixture factories, contract test scaffolding, request recorder

### Resources
- Users: list, get, create, update, delete, useUser, useUsers, useUsersInfinite, useUpdateUser, useDeleteUser
- Posts: list, get, create, update, delete, usePost, usePosts, usePostsInfinite
- ...

### Usage
```typescript
import { ApiClient, UserId } from './api';
import { useUser, useUpdateUser } from './api/hooks';

// Direct client usage
const api = new ApiClient({
  baseUrl: 'https://api.example.com',
  auth: { type: 'bearer', getToken: () => getAccessToken() },
});
const users = await api.users.list({ page: 1 });

// React Query hooks
function UserProfile({ id }: { id: UserId }) {
  const { data: user } = useUser(id);
  const updateUser = useUpdateUser();
  // optimistic updates handled automatically
}

// Real-time events
const ws = new TypedWebSocketClient({ url: 'wss://api.example.com/ws', getAuthToken });
ws.on('user.updated', (user) => queryClient.setQueryData(queryKeys.users.detail(user.id), user));
```

### Testing
```typescript
import { setupServer } from 'msw/node';
import { handlers, errorHandlers } from './api/testing/handlers';
import { fixtures } from './api/testing/fixtures';

const server = setupServer(...handlers);
// Override for error scenarios:
server.use(errorHandlers.rateLimited);
```

### Next Steps
- Configure base URL and authentication credentials per environment
- Run `/genskills:test-generator` to add integration tests for the client
- Set up MSW in your test runner for offline testing
- Consider distributing as a package if consumed by multiple apps
```

## Configuration

- `httpLibrary`: string - preferred HTTP library (default: auto-detect from project)
- `outputDir`: string - output directory for generated code
- `generateTests`: boolean - generate MSW handlers, fixtures, and contract test scaffolding (default: false)
- `includeReactHooks`: boolean - generate React Query / TanStack Query hooks (default: auto-detect)
- `includeTrpc`: boolean - generate tRPC client layer when source is a tRPC router (default: auto-detect)
- `includeRealtime`: boolean - generate WebSocket/SSE/long-polling clients (default: true if spec contains WS/SSE endpoints)
- `authStrategy`: `"bearer"` | `"oauth2-pkce"` | `"api-key"` | `"session"` | `"multi-tenant"` | `"custom"` - auth pattern to generate (default: inferred from spec)
- `retryStrategy`: `"default"` | `"aggressive"` | `"none"` | `{ maxRetries, backoff }` - retry behavior (default: `"default"`)
- `enableCircuitBreaker`: boolean - include circuit breaker logic (default: true)
- `cacheStrategy`: `"none"` | `"swr"` | `"stale-if-error"` - response caching pattern (default: `"none"`)
- `middleware`: string[] - middleware to include: `["logging", "dedup", "compression", "signing"]` (default: `["logging"]`)
- `piiRedaction`: boolean - enable PII redaction in logs (default: true)
- `sdkPackage`: boolean - scaffold as distributable npm package with exports map (default: false)
- `brandedIds`: boolean - generate branded types for entity IDs (default: true)
- `strictNulls`: boolean - distinguish between `null` and `undefined` in optional fields (default: true)
- `queryComplexityLimit`: number - max GraphQL query complexity before warning (default: 1000)
- `persistedQueries`: boolean - generate persisted query hashes for GraphQL (default: false)
