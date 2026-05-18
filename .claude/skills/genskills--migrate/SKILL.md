---
name: genskills:migrate
description: >
  Assist with code migrations - framework upgrades, API changes,
  dependency updates, pattern modernization. Triggers on: "migrate",
  "upgrade", "update framework", "convert to", "move from X to Y".
user-invocable: true
argument-hint: "[from] [to] - e.g., 'react-router v5 v6' or 'jest vitest'"
allowed-tools: "Read, Edit, Write, Grep, Glob, WebFetch, Bash(npm *), Bash(npx *), Bash(pip *)"
genskills-version: "1.4.2"
genskills-category: "development"
genskills-depends: []
---

# Migrate

Assist with code, dependency, data, infrastructure, and build-system migrations. This skill covers everything from single-library version bumps to full architectural rewrites, with emphasis on incremental safety, rollback capability, and zero-downtime strategies.

---

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any migration policies documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Identify the project's language, framework, package manager, and CI system
- Read lock files (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `Pipfile.lock`, `poetry.lock`) to understand the current dependency graph

### Step 1: Understand the Migration
Parse `$ARGUMENTS`:
- `$0` = library/framework name or "from" pattern
- `$1` = source version/pattern (or auto-detect from package.json/lock file)
- `$2` = target version/pattern (default: "latest")

---

## Migration Catalog

### Framework Version Upgrades
- React 17 to 18 (concurrent features, automatic batching, `createRoot`)
- React 18 to 19 (React Compiler, `use()` hook, server components stabilization)
- Next.js 13 to 14 to 15 (App Router, Server Actions, Turbopack, async request APIs)
- Vue 2 to 3 (Composition API, `<script setup>`, Teleport, Pinia over Vuex)
- Angular version upgrades (schematic-based: `ng update @angular/core@<version>`, handling RxJS changes, standalone components migration, signal-based reactivity)
- Svelte 4 to 5 (runes, snippets, event changes)
- Django 3.x to 4.x to 5.x (async views, psycopg3, field changes)
- Rails major version upgrades (autoloading changes, encrypted credentials)
- Python 2 to 3 (see dedicated section below)

### Testing Framework Switches
- Jest to Vitest (config mapping, globals, mocking API differences, snapshot format)
- Enzyme to Testing Library (shallow rendering removal, query-by-role, user-event)
- Mocha/Chai to Jest or Vitest
- Cypress to Playwright (selector strategies, auto-waiting differences, fixture handling)
- unittest to pytest (fixtures, parametrize, conftest patterns)

### Package Manager Changes
- npm to pnpm (workspace config, `.npmrc` to `.npmrc` with `shamefully-hoist`, lock file conversion)
- Yarn v1 (Classic) to Yarn v4 (Berry) (PnP vs node_modules, `.yarnrc.yml`, constraints, patches)
- npm to Bun (lock file, script runner, built-in test runner)

### API Pattern Changes
- REST to GraphQL (schema design, resolver mapping, client generation with codegen, N+1 prevention with DataLoader)
- REST to tRPC (router definition, input validation with Zod, client/server type sharing, middleware chains)
- Callbacks to async/await (promisify patterns, error handling migration)
- CommonJS to ESM (see dedicated section below)

### CSS and Styling Changes
- CSS Modules to Tailwind CSS (utility extraction, design token mapping)
- styled-components / Emotion to Tailwind CSS or CSS Modules
- Sass/LESS to CSS custom properties and modern CSS (nesting, `@layer`, `color-mix()`)
- CSS-in-JS to zero-runtime alternatives (Panda CSS, vanilla-extract, StyleX)

### State Management Migrations
- Redux (+ Redux Toolkit) to Zustand (store slicing, middleware mapping, devtools)
- Redux to Jotai (atom-based decomposition, derived atoms for selectors, async atoms for thunks)
- Redux to Recoil (atoms, selectors, `useRecoilState` mapping)
- MobX to Zustand or native React state
- Vuex to Pinia (module-to-store mapping, composition API stores)

### Build System Migrations
- Webpack to Vite (config translation, plugin equivalents, HMR differences, `import.meta.env` vs `process.env`, asset handling)
- Webpack to Turbopack (Next.js integrated, limited standalone config)
- Create React App to Vite (eject considerations, env variable prefix `REACT_APP_` to `VITE_`, public path changes)
- Rollup to esbuild or tsup for library builds
- Gulp/Grunt to npm scripts or Turborepo tasks

### Server Framework Migrations
- Express to Fastify (plugin system, schema validation, decorators, lifecycle hooks, serialization)
- Express to Hono (lightweight handlers, middleware mapping, multi-runtime support)
- Express to Koa (middleware composition differences, `ctx` pattern)
- Flask to FastAPI (type hints, Pydantic models, async routes, dependency injection)
- Spring Boot version upgrades (Jakarta namespace migration from `javax.*`)

### ORM and Database Migrations
- SQLAlchemy 1.x to 2.x (declarative mapping v2 style, `Session.execute()` over `Query`, `mapped_column()`, type annotations, `select()` based queries)
- Sequelize to Prisma (schema definition, migration generation, type-safe client)
- TypeORM to Prisma or Drizzle
- Mongoose to Prisma (for SQL migration from MongoDB)
- Django ORM version changes (field deprecations, constraint additions)

### Architectural Migrations
- Monolith to microservices (see dedicated section below)
- Class components to hooks (see dedicated section below)
- Pages Router to App Router (Next.js)
- Options API to Composition API (Vue)

### CI/CD Migrations
- Jenkins to GitHub Actions (see dedicated section below)
- CircleCI to GitHub Actions (see dedicated section below)
- Travis CI to GitHub Actions
- GitLab CI to GitHub Actions

---

## Incremental Migration Strategies

Every large migration should be incremental. Never attempt a big-bang rewrite unless the codebase is trivially small. Choose a strategy:

### Strangler Fig Pattern
Gradually replace old code by wrapping it. New requests/features use the new system; old code remains until all paths are migrated.

```
1. Identify a boundary (route, module, feature)
2. Build the new implementation alongside the old
3. Route traffic/imports to the new implementation
4. Once validated, remove the old code
5. Repeat for the next boundary
```

Practical application:
- **Monolith to microservices**: extract one bounded context at a time behind an API gateway
- **Framework migration**: new pages use the new framework; old pages stay until ported
- **API versioning**: `/api/v2/` endpoints use the new stack; `/api/v1/` remains

### Adapter / Anti-Corruption Layer
Place an adapter between old and new code so each side speaks its own language.

```typescript
// Adapter: old Redux store shape → new Zustand interface
function adaptLegacyStore(reduxState: LegacyState): NewStoreShape {
  return {
    user: reduxState.auth.currentUser,
    items: reduxState.entities.items.allIds.map(id => reduxState.entities.items.byId[id]),
    // ... map every field
  };
}
```

Use adapters when:
- Two systems must coexist during migration
- External consumers depend on the old interface
- Database schemas differ between old and new

### Feature Flags for Gradual Rollout
Use feature flags to control which code path executes at runtime.

```typescript
// Using a feature flag service or simple env toggle
if (featureFlags.isEnabled('use-new-auth-service')) {
  return newAuthService.authenticate(req);
} else {
  return legacyAuthService.authenticate(req);
}
```

Strategy:
1. Wrap migrated code behind a flag
2. Enable for internal users / staging first
3. Roll out to a percentage of production traffic (1% → 10% → 50% → 100%)
4. Monitor error rates and performance at each step
5. Remove the flag and old code once at 100% with confidence

### Parallel Running (Old + New)
Run both implementations simultaneously, compare outputs, but only serve the old result. Once confidence is high, switch to serving the new result.

**Template:** `templates/parallel-running.ts`
Run both old and new handlers, log discrepancies, serve old result until confident.

Best for: database queries, API responses, calculation engines - anywhere correctness is paramount.

### Canary Migration (One Module First)
Pick the simplest, most isolated module. Migrate it fully. Learn from the experience, refine your approach, then migrate the rest.

Selection criteria for the canary:
- Few external dependencies
- Good test coverage
- Low risk if it breaks
- Representative of other modules

Document every issue encountered during the canary. Build a runbook for the remaining modules.

---

## Detailed Migration Guides

### CommonJS to ESM

This is one of the most common and most error-prone migrations. Follow this strategy:

**Phase 1: Preparation**
```bash
# Audit current CJS usage
grep -r "require(" src/ --include="*.js" --include="*.ts" -l | wc -l
grep -r "module.exports" src/ --include="*.js" --include="*.ts" -l | wc -l
```

**Phase 2: package.json**
```json
{
  "type": "module",
  "exports": {
    ".": {
      "import": "./dist/index.mjs",
      "require": "./dist/index.cjs"
    }
  }
}
```

**Phase 3: File-by-file conversion**
**Template:** `templates/cjs-to-esm-conversion.js`
Side-by-side CJS require/module.exports to ESM import/export conversion examples.

**Key gotchas**:
- ESM requires file extensions in relative imports (`.js`, `.mjs`)
- `__dirname` and `__filename` do not exist in ESM - use `import.meta.url` with `fileURLToPath`
- `require.resolve` becomes `import.meta.resolve` (or use `createRequire`)
- Dynamic `require()` becomes dynamic `import()` (returns a Promise)
- JSON imports need `assert { type: 'json' }` or `with { type: 'json' }` (Node 22+)
- Top-level `await` is available in ESM
- Circular dependencies behave differently - ESM gives live bindings, CJS gives snapshot values

**Phase 4: Config files**
Many tools still expect CJS config. Options:
- Rename to `.cjs` extension (`jest.config.cjs`, `knexfile.cjs`)
- Use the tool's ESM support if available (e.g., Vite and Rollup natively support ESM config)

**Phase 5: Dual publishing (for libraries)**
Use a build tool (tsup, unbuild, pkgroll) to emit both formats:
**Template:** `templates/dual-publish-package.json`
Package.json exports config for dual CJS/ESM publishing with type declarations.

### Python 2 to 3

**Automated tools**:
- `2to3` - standard library tool for automatic conversion
- `futurize` (from `python-future`) - writes code compatible with both 2 and 3
- `modernize` - similar to futurize, targets Python 3 only

**Key patterns**:
**Template:** `templates/python2-to-python3-patterns.py`
Side-by-side Py2 vs Py3 patterns for print, division, unicode, dicts, range, imports, exceptions, and metaclasses.

**Strategy**: use `futurize` in stages. Stage 1 applies safe, mechanical fixes. Stage 2 handles more complex patterns that may need manual review.

### Class Components to Hooks (React)

**Migration order** (least risky first):
1. Pure presentational components (just props → JSX)
2. Components using only `setState`
3. Components with lifecycle methods
4. Components with complex `shouldComponentUpdate`
5. Higher-order components → custom hooks
6. Components using `context` with `contextType`

**Pattern mappings**:
**Template:** `templates/class-components-to-hooks.tsx`
Mappings for state, lifecycle methods, refs, context, and instance variables from class components to hooks.

**Important**: `componentDidCatch` and `getDerivedStateFromError` have no hook equivalents. Error boundary components must remain as classes (or use a library like `react-error-boundary`).

### Monolith to Microservices

**Phase 1: Identify bounded contexts**
- Map the domain model - find natural seams
- Look for modules with minimal cross-dependencies
- Identify the data each context owns

**Phase 2: Define service boundaries**
- Each service owns its data store (database-per-service)
- Define contracts (API schemas, event schemas)
- Decide on communication: synchronous (HTTP/gRPC) vs asynchronous (message queue)

**Phase 3: Extract using Strangler Fig**
```
Monolith                          Microservice
┌─────────────┐    API Gateway    ┌──────────┐
│  /users/*   │ ──────────────→   │ User Svc │
│  /orders/*  │ (still in mono)   └──────────┘
│  /payments/*│ (still in mono)
└─────────────┘
```

1. Extract the canary service (e.g., notifications, user profiles)
2. Set up an API gateway or reverse proxy to route
3. Implement an anti-corruption layer for shared data
4. Migrate data ownership to the new service
5. Repeat for each bounded context

**Phase 4: Handle shared data**
- Saga pattern for distributed transactions
- Event sourcing for cross-service data consistency
- CQRS to separate read/write models across services

**Common pitfalls**:
- Distributed monolith (services too tightly coupled)
- Shared database anti-pattern
- Synchronous chains creating latency and fragility
- Premature extraction (extract too many services too early)

### REST to GraphQL

**Strategy**: run both side by side; never cut over all at once.

1. **Schema design**: model your domain as a graph, not as REST endpoints
2. **Resolver mapping**: each resolver can call the existing REST endpoint internally
3. **Client migration**: replace `fetch('/api/users')` with GraphQL queries one screen at a time
4. **Deprecation**: once all clients use GraphQL, remove REST endpoints

**Template:** `templates/rest-to-graphql-resolver.ts`
GraphQL resolver that wraps an existing REST endpoint during incremental migration.

**REST to tRPC** follows the same incremental approach but with the advantage of full type safety end-to-end. Define your tRPC router, create procedures matching your REST endpoints, and migrate clients one call at a time.

### Redux to Zustand

**Template:** `templates/redux-to-zustand.ts`
Side-by-side Redux Toolkit slice vs equivalent Zustand store with typed interface.

**Migration strategy**:
1. Install Zustand alongside Redux
2. Create Zustand stores mirroring Redux slices one at a time
3. Update components consuming each slice to use `useUserStore()` instead of `useSelector`/`useDispatch`
4. For async logic, replace thunks with async functions in the store or extract to utility functions
5. Remove the Redux slice once all consumers are migrated
6. Remove Redux entirely once all slices are migrated

**For Redux to Jotai**: decompose each slice into individual atoms. Derived data becomes derived atoms (`atom((get) => ...)`). Async operations become async atoms.

### Webpack to Vite

**Config translation cheat sheet**:
| Webpack | Vite |
|---------|------|
| `entry` | `build.rollupOptions.input` (or automatic from `index.html`) |
| `output.publicPath` | `base` |
| `resolve.alias` | `resolve.alias` (same) |
| `devServer.proxy` | `server.proxy` |
| `module.rules` (loaders) | Plugins or built-in support |
| `DefinePlugin` | `define` |
| `process.env.NODE_ENV` | `import.meta.env.MODE` |
| `process.env.REACT_APP_*` | `import.meta.env.VITE_*` |
| `HtmlWebpackPlugin` | Built-in (uses `index.html` at root) |
| `MiniCssExtractPlugin` | Built-in |
| `CopyWebpackPlugin` | `vite-plugin-static-copy` or `public/` dir |

**Steps**:
1. Move `index.html` to project root, add `<script type="module" src="/src/main.tsx"></script>`
2. Install Vite: `npm install -D vite @vitejs/plugin-react` (or `plugin-vue`, etc.)
3. Create `vite.config.ts` mapping from webpack config
4. Replace `process.env.REACT_APP_*` with `import.meta.env.VITE_*` across codebase
5. Replace `require()` with `import` (Vite is ESM-first)
6. Replace `require.context` with `import.meta.glob`
7. Update `package.json` scripts: `"dev": "vite"`, `"build": "vite build"`
8. Handle CommonJS dependencies - Vite's dependency pre-bundling usually handles this, but some may need `optimizeDeps.include`

### Express to Fastify

**Template:** `templates/express-to-fastify.ts`
Express route handler converted to Fastify with schema validation and typed params.

**Key differences**:
- Fastify uses a plugin system instead of middleware - use `fastify.register()` and `fastify-plugin`
- Schema-based validation and serialization (much faster JSON output)
- Lifecycle hooks (`onRequest`, `preParsing`, `preValidation`, `preHandler`, `preSerialization`, `onSend`, `onResponse`) replace Express middleware ordering
- Decorators (`fastify.decorate`, `fastify.decorateRequest`) replace `req.customProperty` patterns
- Use `@fastify/express` plugin to run Express middleware during migration

### Express to Hono

**Template:** `templates/express-to-hono.ts`
Express route handler converted to Hono's context-based API pattern.

Hono runs on Node, Deno, Bun, Cloudflare Workers, and more. Use it when migrating to edge runtimes.

### SQLAlchemy 1.x to 2.x

**Key changes**:

**Template:** `templates/sqlalchemy-1x-to-2x-declarative.py`
Declarative model mapping migrated from 1.x Column style to 2.x Mapped/mapped_column style.

**Template:** `templates/sqlalchemy-1x-to-2x-query.py`
Query API migrated from 1.x session.query() to 2.x select() style.

**Migration steps**:
1. Enable SQLAlchemy 2.0 deprecation warnings: `SQLALCHEMY_WARN_20=1`
2. Run test suite - every warning indicates code to migrate
3. Replace `session.query()` with `select()` + `session.execute()` patterns
4. Update declarative base to the new `DeclarativeBase` class
5. Add `Mapped[]` type annotations to columns
6. Replace `declarative_base()` with class-based `DeclarativeBase`
7. Update relationship definitions to use `Mapped[]` with `relationship()`

### Angular Version Upgrades

Angular provides schematics for automated migration:

```bash
# Always update one major version at a time
ng update @angular/core@16 @angular/cli@16
ng update @angular/core@17 @angular/cli@17
ng update @angular/core@18 @angular/cli@18
ng update @angular/core@19 @angular/cli@19

# Check what the update will do first
ng update @angular/core@17 --dry-run
```

**Common breaking changes by version**:
- **v15 → v16**: Required signals foundation, standalone components by default
- **v16 → v17**: New control flow syntax (`@if`, `@for`, `@switch`), deferrable views (`@defer`)
- **v17 → v18**: Zoneless change detection (experimental), signal-based inputs/outputs
- **v18 → v19**: Signal-based components stable, `inject()` preferred over constructor injection

**Standalone component migration**:
```bash
ng generate @angular/core:standalone
```
This schematic converts NgModule-based components to standalone components automatically.

---

## Rollback Strategies

Every migration must have a rollback plan. Define it before starting.

### Feature Flag Rollback
The safest rollback: flip the flag back to the old code path.

```typescript
// Rollback is instant - no deployment needed
featureFlags.disable('use-new-payment-service');
```

Requirements:
- Both old and new code paths are deployed
- The flag service is reliable and fast
- State is compatible (new code must not write data the old code cannot read)

### Database Backward-Compatible Migrations

**Expand-Contract pattern** (safe for zero-downtime rollback):

```
Phase 1 - Expand:
  - Add new column (nullable or with default)
  - Deploy code that writes to BOTH old and new columns
  - Backfill new column from old column

Phase 2 - Migrate:
  - Deploy code that reads from new column
  - Verify correctness

Phase 3 - Contract:
  - Deploy code that stops writing old column
  - Drop old column (only after confidence period)
```

**Rules for backward-compatible schema changes**:
- NEVER rename a column in one step (add new, migrate, drop old)
- NEVER change a column type in one step (add new column, migrate data, drop old)
- NEVER add a NOT NULL constraint without a default on an existing column
- Adding a column: always nullable or with a default
- Dropping a column: first remove all code that reads/writes it, then drop
- Adding an index: use `CREATE INDEX CONCURRENTLY` (Postgres) to avoid locks

### Blue-Green Deployment During Migration
Run two complete environments:
- **Blue**: current production (old code)
- **Green**: new code

Route all traffic to Blue. Test Green thoroughly. Switch the router to Green. If problems arise, switch back to Blue instantly.

Best for: infrastructure migrations, major version upgrades, database engine changes.

### Rollback Script Generation
For every migration step, generate a corresponding rollback:

```bash
# migration_001_add_users_table.sql
CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT NOT NULL);

# migration_001_add_users_table_rollback.sql
DROP TABLE IF EXISTS users;
```

For code changes, rely on version control:
```bash
# Tag before migration
git tag pre-migration-<name>

# Rollback if needed
git revert --no-commit HEAD~<N>..HEAD
git commit -m "Rollback: revert <migration-name>"
```

---

## Dependency Conflict Resolution

### Peer Dependency Conflicts
```bash
# Diagnose
npm ls <package-name>           # Show dependency tree for a package
npm explain <package-name>      # Explain why a package is installed (npm 8+)
npm ls --all | grep "UNMET"     # Find all unmet peer deps

# Fix options (in order of preference):
# 1. Update the conflicting package to a compatible version
npm update <package-name>

# 2. Use --legacy-peer-deps (delays the problem)
npm install --legacy-peer-deps

# 3. Use overrides to force a version (npm 8.3+)
```

### Transitive Dependency Issues
A dependency of a dependency causes problems.

```bash
# Find who depends on the problematic package
npm ls <problematic-package>

# Visualize the full tree
npm ls --all > dependency-tree.txt
```

Solutions:
1. Update the direct dependency that pulls in the bad transitive dep
2. Use `overrides` (npm) or `resolutions` (Yarn) to force a version
3. Use `patch-package` for temporary source-level fixes

### Version Pinning Strategies

**In `package.json`**:
```json
{
  "overrides": {
    "vulnerable-package": "2.0.1",
    "parent-package>child-package": "1.5.0"
  }
}
```

**Yarn `resolutions`** (Yarn Classic and Berry):
```json
{
  "resolutions": {
    "vulnerable-package": "2.0.1",
    "**/child-package": "1.5.0"
  }
}
```

**pnpm `overrides`** in `package.json`:
```json
{
  "pnpm": {
    "overrides": {
      "vulnerable-package": "2.0.1"
    }
  }
}
```

### patch-package for Temporary Fixes

When a dependency has a bug and no fix is released yet:

**Template:** `templates/patch-package-workflow.bash`
Step-by-step patch-package workflow: fix in node_modules, generate patch, add postinstall hook.

For pnpm, use the built-in `pnpm patch` command:
```bash
pnpm patch <package-name>@<version>
# Edit the temporary directory
pnpm patch-commit <temp-dir>
```

---

## Large-Scale Migration Tools

### AST-Based Transforms with jscodeshift

jscodeshift is Facebook's toolkit for running codemods over JavaScript/TypeScript codebases.

```bash
# Run an existing codemod
npx jscodeshift -t <transform-file-or-url> <target-path>

# Common community codemods
npx jscodeshift -t react-codemod/transforms/rename-unsafe-lifecycles.js src/
npx jscodeshift -t @next/codemod/transforms/next-og-import.js src/
```

**Writing a custom jscodeshift transform**:
**Template:** `templates/jscodeshift-transform.js`
Custom jscodeshift transform that converts require() calls to ESM import declarations.

### AST-Based Transforms with ts-morph

ts-morph provides a TypeScript-aware API for programmatic code transformations:

**Template:** `templates/ts-morph-transform.ts`
ts-morph script that renames interfaces and adds missing return types across a TypeScript project.

**When to use which**:
- **jscodeshift**: JavaScript-heavy codebases, existing community transforms, AST Explorer-friendly prototyping
- **ts-morph**: TypeScript-heavy codebases, need type-aware transforms, renaming with full reference tracking

### Custom Codemod Authoring Guide

1. **Prototype** in [AST Explorer](https://astexplorer.net/) - select the correct parser (babel, typescript, etc.)
2. **Write the transform** - handle all edge cases (destructured imports, re-exports, aliased names)
3. **Test on a single file** before running on the full codebase
4. **Run in dry mode**: `npx jscodeshift --dry --print -t transform.js src/`
5. **Run for real**: `npx jscodeshift -t transform.js src/`
6. **Review the diff**: `git diff` - verify the transform did not mangle anything
7. **Run tests** to catch semantic breakage

### Parallel File Processing for Large Codebases

jscodeshift runs transforms in parallel by default (using workers):
```bash
# Adjust parallelism
npx jscodeshift -t transform.js --cpus=8 src/

# Process specific file patterns
npx jscodeshift -t transform.js --extensions=tsx,ts --ignore-pattern="**/*.test.*" src/
```

For custom tools, use worker threads or process pools:
**Template:** `templates/parallel-file-processing.ts`
Worker threads pool that distributes migration file processing across all CPU cores.

---

## Testing During Migration

### Dual Testing (Old and New)
Run tests against both implementations to ensure behavioral equivalence:

**Template:** `templates/dual-testing.ts`
Test suite using describe.each to run the same assertions against both legacy and new implementations.

### Snapshot Comparison
Capture output snapshots from the old code, then verify the new code produces identical results:

**Template:** `templates/snapshot-comparison.ts`
Two-phase approach: capture output snapshots from old code, then verify new code matches them.

### API Contract Testing
When migrating an API backend, use contract tests to ensure the new implementation honors the same contract:

**Template:** `templates/api-contract-testing.ts`
Supertest-based contract tests verifying response shape and status codes for API endpoints.

For consumer-driven contract testing, use Pact:
```bash
npm install -D @pact-foundation/pact
```

### Visual Regression Testing
When migrating UI frameworks or component libraries, use visual regression to catch rendering differences:

```bash
# Playwright visual comparison
npx playwright test --update-snapshots   # Before migration: capture baselines
# ... perform migration ...
npx playwright test                       # After: compare against baselines
```

Tools: Playwright (built-in), Chromatic (Storybook), Percy, BackstopJS.

Strategy:
1. Capture baseline screenshots on every page/component before migration
2. Perform migration
3. Run screenshot comparison - review all diffs
4. Update baselines for intentional changes

---

## Type Migration

### JavaScript to TypeScript (Gradual)

**Phase 1: Setup**
**Template:** `templates/tsconfig-gradual-migration.json`
Permissive tsconfig.json starter for gradual JS-to-TS migration with allowJs and no strict checks.

**Phase 2: Rename files**
Start with leaf files (no other file imports them) and work inward:
```bash
# Rename .js → .ts (or .jsx → .tsx)
# Start with utility files, then models, then components, then pages
mv src/utils/format.js src/utils/format.ts
```

**Phase 3: Add types incrementally**
```typescript
// Start with explicit any - it compiles
function processData(data: any): any { ... }

// Then tighten
function processData(data: RawRecord[]): ProcessedRecord[] { ... }
```

**Phase 4: Increase strictness** (one flag at a time in `tsconfig.json`)
```
noImplicitAny: true          // First - most impactful
strictNullChecks: true       // Second - catches null bugs
strictFunctionTypes: true    // Third
strictBindCallApply: true    // Fourth
strict: true                 // Finally - all checks
```

### `any` Elimination Strategies

```bash
# Count remaining `any` usage
grep -r ": any" src/ --include="*.ts" --include="*.tsx" -c
```

**Techniques**:
1. **Explicit types**: replace `any` with the actual type
2. **`unknown` + narrowing**: when the type truly is unknown at compile time
   ```typescript
   function parse(input: unknown): Config {
     if (typeof input === 'object' && input !== null && 'name' in input) {
       return input as Config; // Narrowed safely
     }
     throw new Error('Invalid config');
   }
   ```
3. **Generics**: when the type varies by call site
   ```typescript
   function identity<T>(x: T): T { return x; }
   ```
4. **Template literal types** and **conditional types** for complex patterns
5. **Zod / io-ts / valibot**: runtime validation that generates TypeScript types
   ```typescript
   import { z } from 'zod';
   const UserSchema = z.object({ name: z.string(), age: z.number() });
   type User = z.infer<typeof UserSchema>; // No `any` needed
   ```

### PropTypes to TypeScript

**Template:** `templates/proptypes-to-typescript.tsx`
Button component migrated from PropTypes/defaultProps to TypeScript interface with default parameter values.

**PropTypes to TypeScript mapping**:
| PropTypes | TypeScript |
|-----------|-----------|
| `PropTypes.string` | `string` |
| `PropTypes.number` | `number` |
| `PropTypes.bool` | `boolean` |
| `PropTypes.func` | `() => void` (or specific signature) |
| `PropTypes.array` | `unknown[]` (or typed array) |
| `PropTypes.object` | `Record<string, unknown>` (or specific interface) |
| `PropTypes.node` | `React.ReactNode` |
| `PropTypes.element` | `React.ReactElement` |
| `PropTypes.oneOf(['a','b'])` | `'a' \| 'b'` |
| `PropTypes.oneOfType([...])` | Union type |
| `PropTypes.arrayOf(PropTypes.string)` | `string[]` |
| `PropTypes.shape({...})` | `interface` |
| `PropTypes.exact({...})` | `interface` (exact matching via type) |
| `.isRequired` | Remove `?` from property |

### Flow to TypeScript

```bash
# Automated tool
npx flow-to-ts --write src/**/*.js
```

**Key differences to fix manually**:
**Template:** `templates/flow-to-typescript-patterns.ts`
Mapping of Flow utility types to their TypeScript equivalents.

---

## Data Migration

### Database Schema + Data Migration Coordination

**Principle**: schema changes and data changes must be coordinated with code deployments.

**Order of operations**:
```
1. Deploy code that handles BOTH old and new schema  ← Forward-compatible
2. Run schema migration (add columns, tables)
3. Run data migration (backfill, transform)
4. Deploy code that uses only the new schema
5. Run cleanup migration (drop old columns)          ← Only after confidence period
```

### ETL Patterns for Data Migration

**Template:** `templates/etl-data-migration.py`
ETL function that extracts from legacy schema, transforms field mappings, loads in batches, and validates row counts.

### Zero-Downtime Data Migration

**Strategy 1: Dual-write**
```
1. Deploy code that writes to BOTH old and new stores
2. Backfill historical data from old → new
3. Verify parity
4. Switch reads to new store
5. Stop writing to old store
6. Decommission old store
```

**Strategy 2: CDC (Change Data Capture)**
Use a tool like Debezium, DMS, or database-native replication to stream changes from old to new in real-time:
```
Old DB → CDC stream → Transform → New DB
         (Debezium)   (Kafka/Lambda)
```

**Strategy 3: Online migration with ghost tables** (for MySQL: `gh-ost`, for Postgres: `pgroll`)
```bash
# gh-ost example - online schema migration for MySQL
gh-ost \
  --host=db.example.com \
  --database=myapp \
  --table=users \
  --alter="ADD COLUMN phone VARCHAR(20)" \
  --execute
```

### Data Validation After Migration

Always validate after migrating data:

**Template:** `templates/data-validation.py`
Post-migration validation checking row counts, null values, duplicates, and date ranges.

**Checksum comparison** for large tables:
```sql
-- Old system
SELECT MD5(GROUP_CONCAT(CONCAT(id, name, email) ORDER BY id)) FROM legacy_users;
-- New system
SELECT MD5(GROUP_CONCAT(CONCAT(id, full_name, email) ORDER BY id)) FROM users;
```

---

## CI/CD Migration

### Jenkins to GitHub Actions

**Concept mapping**:
| Jenkins | GitHub Actions |
|---------|---------------|
| Jenkinsfile (pipeline) | `.github/workflows/*.yml` |
| `stage` | `jobs.<id>` |
| `step` | `jobs.<id>.steps[*]` |
| `agent` / `node` | `runs-on` |
| `when { branch 'main' }` | `on.push.branches: [main]` |
| `environment` / `withCredentials` | `env` + `secrets.*` |
| `post { always { ... } }` | `if: always()` on a step |
| `parallel` | Multiple jobs (run in parallel by default) |
| Shared libraries | Composite actions or reusable workflows |
| `parameters` | `workflow_dispatch.inputs` |
| Artifacts (archiveArtifacts) | `actions/upload-artifact` |

**Example conversion**:
**Template:** `templates/jenkinsfile-example.groovy`
Sample Jenkinsfile with install, test, build, and conditional deploy stages.

**Template:** `templates/jenkins-to-github-actions.yml`
Equivalent GitHub Actions workflow with build and conditional deploy jobs.

**Migration checklist**:
1. Map all Jenkins credentials to GitHub Actions secrets
2. Convert Shared Libraries to composite actions or reusable workflows (`workflow_call`)
3. Replace Jenkins plugins with GitHub Actions marketplace equivalents
4. Convert `Jenkinsfile` parameterized builds to `workflow_dispatch` inputs
5. Set up branch protection rules to replace Jenkins gatekeeping
6. Migrate Jenkins artifact storage to GitHub Actions artifacts or external storage
7. Run both systems in parallel during transition (Jenkins + GHA on same PRs)

### CircleCI to GitHub Actions

**Concept mapping**:
| CircleCI | GitHub Actions |
|----------|---------------|
| `.circleci/config.yml` | `.github/workflows/*.yml` |
| `jobs` | `jobs` |
| `workflows` | `on` triggers + job dependencies |
| `orbs` | Actions from marketplace |
| `executors` | `runs-on` + `container` |
| `persist_to_workspace` / `attach_workspace` | `actions/upload-artifact` + `actions/download-artifact` |
| `store_test_results` | Third-party test reporter actions |
| `cache` (with keys) | `actions/cache@v4` |
| `context` | Environment secrets |
| `filters.branches` | `on.push.branches` / `on.pull_request.branches` |

**Example conversion**:
**Template:** `templates/circleci-config-example.yml`
Sample CircleCI config with Node orb, Postgres service, test and deploy jobs.

**Template:** `templates/circleci-to-github-actions.yml`
Equivalent GitHub Actions workflow with Postgres service container and conditional deploy.

### Build System Migration Validation

After migrating CI/CD, validate that the new pipeline produces identical outcomes:

1. **Output comparison**: build artifacts from old and new pipelines should match (compare checksums)
2. **Timing comparison**: new pipeline should not be significantly slower
3. **Coverage parity**: test coverage numbers should match
4. **Deployment parity**: deploy to a staging environment from both pipelines, compare
5. **Notification parity**: Slack/email notifications still fire correctly
6. **Secret rotation**: old CI system's secrets should be rotated after decommission

---

## Migration Execution

### Step 2: Research Breaking Changes
- Check the official migration guide if available (search for `<library> migration guide <version>`)
- Read the CHANGELOG of the target package for breaking changes
- Identify deprecated APIs that need replacement
- Check for available codemods: `npx @codemod/...`, `npx jscodeshift`, `npx @next/codemod`, `npx @angular/cli update`

### Step 3: Assess Impact
- Search the codebase for usage of deprecated/changed APIs using Grep
- Count affected files and list them
- Categorize changes: automatic (codemod available), semi-automatic (pattern replacement), manual (requires judgment)
- Check dependency compatibility - will other packages conflict?
- Estimate scope: small (< 10 files), medium (10-50 files), large (50+ files)
- Identify rollback strategy before proceeding

### Step 4: Execute Migration
In this order:
1. **Tag the pre-migration state**: `git tag pre-migration-<name>`
2. **Update dependencies**: `package.json` / `requirements.txt` / lock file
3. **Run codemods** if available - apply automated transforms first
4. **Update configuration files**: framework config, build config, test config
5. **Apply API changes** file by file - start with leaf files (no dependents), work inward
6. **Fix imports and type changes**: renamed exports, moved modules
7. **Update tests**: adapt test utilities, assertions, mocking patterns
8. **Run dual tests** if both implementations coexist

**Rules**:
- Make one category of change at a time (deps, then config, then code)
- Commit between major steps so progress is preserved
- Don't mix migration changes with unrelated improvements
- Keep a migration log of decisions and issues encountered

### Step 5: Verify
- Run the build to catch compilation errors: `npm run build`
- Run the test suite: `npm test`
- Run the linter: `npm run lint` (migration may introduce lint issues)
- Run type checking: `npx tsc --noEmit` (for TypeScript projects)
- If any step fails, fix the issues before proceeding
- For UI migrations, run visual regression tests if available

### Step 6: Report
**Template:** `templates/migration-report.md`
Structured report template covering changes summary, verification results, rollback plan, and follow-up steps.

---

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `autoCommit`: boolean - commit between migration steps (default: false)
- `dryRun`: boolean - show changes without applying (default: false)
- `skipTests`: boolean - skip test verification (default: false)
- `rollbackTag`: boolean - create a git tag before migration starts (default: true)
- `parallelWorkers`: number - worker count for codemod execution (default: CPU count)
- `migrationStrategy`: string - "big-bang" | "strangler-fig" | "canary" (default: "strangler-fig")
