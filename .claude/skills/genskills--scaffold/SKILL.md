---
name: genskills:scaffold
description: >
  Scaffold new components, modules, services, full-stack features, microservices,
  or entire project structures following existing patterns and conventions.
  Triggers on: "scaffold", "generate component", "create module", "new service",
  "boilerplate", "create page", "new feature", "generate api", "create worker",
  "new plugin", "scaffold cli".
user-invocable: true
argument-hint: "[type] [name] - e.g., 'component UserProfile', 'feature billing', 'microservice payments', 'graphql Mutation.createOrder'"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(npm *), Bash(npx *), Bash(yarn *), Bash(pnpm *), Bash(pip *), Bash(poetry *), Bash(bundle *), Bash(mix *), Bash(cargo *), Bash(dotnet *), Bash(go *)"
genskills-version: "1.4.2"
genskills-category: "development"
genskills-depends: []
---

# Scaffold

Generate new code structures that follow project conventions exactly, from single files to full vertical-slice features spanning UI, API, database, and tests.

## Supported Scaffold Types

| Type keyword | What is generated |
|---|---|
| `component` | UI component + styles + test + barrel export |
| `page` | Page/route component + layout + loading/error states |
| `feature` | **Full vertical slice**: component + API route + DB model + migration + types + test |
| `api` | API route/controller + validation + types + test |
| `service` | Service class/module + interface + test |
| `hook` | Custom React/Vue hook + test |
| `model` | Database model/entity + migration + factory/fixture |
| `graphql` | GraphQL type + resolver + mutation + subscription + test |
| `trpc` | tRPC router + procedures + input schemas + test |
| `middleware` | Middleware function + chain registration + test |
| `worker` | Background job/worker + queue config + retry policy + test |
| `websocket` | WebSocket handler + event types + connection manager + test |
| `cli` | CLI command + argument parser + help text + test |
| `plugin` | Plugin/extension scaffold + manifest + hooks + test |
| `microservice` | Service skeleton with config, health check, Dockerfile, messaging contracts |
| `controller` | Framework-specific controller (NestJS/Spring/Rails/Django/Laravel) |
| `module` | Framework module with imports, providers, exports |
| `pipe` | Data transformation pipe/filter + test |
| `guard` | Auth guard/permission check + test |
| `interceptor` | Request/response interceptor + test |
| `decorator` | Custom decorator/annotation + test |
| `migration` | Database migration file from model diff or description |
| `seed` | Database seed/fixture data file |
| `config` | Configuration module with validation and defaults |

## Process

### Step 0: Load Project Context

- Read `CLAUDE.md` at the project root - follow any scaffolding, naming, or structural conventions documented there
- Read `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Check for `.scaffoldrc`, `.hygen.js`, `plop-templates/`, `schematics/`, or any project-local scaffold configuration
- If `templateDir` is set in config, load custom templates from that directory first and prefer them over auto-detected patterns

### Step 1: Detect Project Patterns

Run a thorough analysis of the existing codebase. Every decision in later steps depends on accurate detection here.

#### 1a. Framework and Runtime Detection

- **JavaScript/TypeScript**: Inspect `package.json` for framework dependencies and scripts
  - React, Next.js (App Router vs Pages Router), Remix, Gatsby
  - Vue 2/3 (Options API vs Composition API), Nuxt 2/3
  - Svelte, SvelteKit
  - Angular (standalone components vs NgModule)
  - Express, Fastify, Hono, Koa
  - NestJS (modules, decorators, DI patterns)
  - tRPC, GraphQL (Apollo, Yoga, Pothos, Nexus, TypeGraphQL)
  - Electron, Tauri
- **Python**: Inspect `pyproject.toml`, `setup.py`, `requirements.txt`, `Pipfile`
  - Django (DRF, Ninja), Flask, FastAPI, Starlette, Litestar
  - Celery, Dramatiq, Huey for background jobs
  - SQLAlchemy, Django ORM, Tortoise ORM, Prisma Client Python
- **Ruby**: Inspect `Gemfile`
  - Rails (API-only vs full-stack), Sinatra, Hanami
  - Sidekiq, GoodJob, Solid Queue for background jobs
- **Java/Kotlin**: Inspect `pom.xml`, `build.gradle`, `build.gradle.kts`
  - Spring Boot, Micronaut, Quarkus, Ktor
- **Go**: Inspect `go.mod`
  - Gin, Echo, Fiber, Chi, standard library
- **Rust**: Inspect `Cargo.toml`
  - Actix Web, Axum, Rocket, Warp
- **Elixir**: Inspect `mix.exs`
  - Phoenix, LiveView
- **C#/.NET**: Inspect `*.csproj`, `*.sln`
  - ASP.NET Core, Minimal APIs, Blazor

#### 1b. Architecture Pattern Detection

Analyze the directory structure and file organization to detect the project's architectural style:

- **Feature-based (vertical slices)**: Code organized by feature/domain
  ```
  src/features/auth/        → components, api, hooks, types all co-located
  src/features/billing/     → same structure per feature
  ```
- **Layer-based (horizontal slices)**: Code organized by technical concern
  ```
  src/components/    → all UI components
  src/services/      → all services
  src/hooks/         → all hooks
  src/models/        → all models
  ```
- **Domain-driven**: Code organized by bounded context
  ```
  src/domains/identity/
  src/domains/catalog/
  src/domains/ordering/
  ```
- **Hybrid**: Features within a layer-based shell (common in larger projects)
  ```
  src/components/auth/LoginForm.tsx
  src/components/auth/RegisterForm.tsx
  src/services/auth/AuthService.ts
  ```

Detect by scanning `src/` (or equivalent) top-level directories and checking whether siblings share a domain name or a technical name.

#### 1c. Convention Detection

Study **2-3 existing examples** of the requested type to learn:

- **Naming conventions**: PascalCase, camelCase, kebab-case, snake_case - for files, directories, classes, functions, variables, database tables, API endpoints
- **File extensions**: `.tsx` vs `.jsx`, `.ts` vs `.js`, `.vue`, `.svelte`, `.module.css` vs `.styles.ts` vs `.css.ts`
- **Export patterns**:
  - Default export vs named export
  - Barrel exports via `index.ts` - detect by checking if `index.ts` files exist in component/feature directories
  - Re-export patterns (`export { default as Foo } from './Foo'` vs `export * from './Foo'`)
- **Import patterns**:
  - Path aliases (`@/`, `~/`, `#/`)
  - Import ordering (external → internal → relative; type imports separated or inline)
  - Side-effect imports
- **Styling approach**: CSS Modules, Tailwind, styled-components, Emotion, vanilla-extract, Panda CSS, UnoCSS, SCSS modules
- **State management**: Redux (toolkit vs legacy), Zustand, Jotai, Recoil, Pinia, Vuex, MobX, XState, Signals
- **Data fetching**: React Query/TanStack Query, SWR, Apollo Client, URQL, RTK Query, tRPC client
- **Validation library**: Zod, Yup, Joi, class-validator, Valibot, ArkType, Typebox
- **Testing setup**: Jest, Vitest, Testing Library, Playwright, Cypress, pytest, RSpec, JUnit, xUnit
- **ORM/database**: Prisma, Drizzle, TypeORM, Sequelize, Knex, MikroORM, SQLAlchemy, Django ORM, ActiveRecord, Entity Framework, GORM
- **Co-location vs separation**: Tests next to source (`Foo.test.ts` beside `Foo.ts`) vs test mirror tree (`__tests__/`, `tests/`, `spec/`)
- **Type definitions**: Co-located in same file, separate `.types.ts` file, centralized `types/` directory

#### 1d. Monorepo Detection

If the project is a monorepo, identify boundaries:

- **Tool**: Turborepo (`turbo.json`), Nx (`nx.json`), Lerna (`lerna.json`), Rush (`rush.json`), pnpm workspaces (`pnpm-workspace.yaml`), Yarn workspaces, Cargo workspaces, Go workspaces
- **Package boundaries**: Which package should the scaffold live in? Determine from context or ask the user.
- **Shared packages**: Identify shared libraries (e.g., `packages/ui`, `packages/types`, `packages/config`) that the new code should import from rather than duplicating
- **Cross-package imports**: Use the correct import specifier (`@org/package-name` not relative paths across package boundaries)

### Step 2: Parse Arguments and Validate

Parse `$ARGUMENTS`:
- `$0` = type (from the supported types table above)
- `$1+` = name and optional flags

**Name transformation rules** - apply the project's detected naming convention:

| Context | Common conventions |
|---|---|
| React/Vue/Svelte component | PascalCase (`UserProfile`) |
| React hook | camelCase with `use` prefix (`useAuth`) |
| Angular component | kebab-case (`user-profile`) |
| File names | Match project: kebab-case, PascalCase, camelCase, or snake_case |
| CSS class names | Match project: camelCase, kebab-case, BEM |
| Database model | PascalCase singular (`User`) or snake_case singular (`user`) |
| Database table | snake_case plural (`users`) - match ORM convention |
| API endpoint | kebab-case plural (`/api/users`, `/api/order-items`) |
| Python module | snake_case (`user_service.py`) |
| Ruby class | PascalCase (`UserService`), file snake_case (`user_service.rb`) |
| Java/Kotlin class | PascalCase, matching package structure |
| Go package | lowercase single word or snake_case |

**Convention enforcement** - before generating, validate:

1. **Name validity**: The name must conform to the detected naming convention. If it does not, auto-correct and inform the user (e.g., "Renamed `userprofile` to `UserProfile` to match PascalCase component convention").
2. **File location**: The target path must match the project's organizational structure. If the user requests `scaffold component Foo` but the project uses feature-based organization, ask which feature it belongs to rather than dumping it in a flat `components/` directory.
3. **No collisions**: Check that no file at the target path already exists. If it does, warn and ask the user whether to overwrite, extend, or pick a different name.
4. **Import ordering**: When adding imports to existing files, follow the project's import ordering convention (use the detected pattern from Step 1c).

If the type is ambiguous or missing, present the supported types table and ask.

### Step 3: Generate Files

Match the **exact patterns** found in existing code. Never guess - always base generated code on real examples found in the project.

---

#### 3.1 React / Next.js / Remix Component

- `ComponentName.tsx` - component matching existing structure (functional component with hooks, props interface/type, default vs named export)
- `ComponentName.test.tsx` - test file using project's testing setup (only if other components have tests)
- `ComponentName.module.css` | `ComponentName.styles.ts` | inline Tailwind - match styling approach
- `ComponentName.stories.tsx` - Storybook story (only if `.stories.` files exist in project)
- `index.ts` - barrel export (only if this pattern exists in sibling components)

**Next.js App Router Page**:
- `app/<route>/page.tsx` - page component
- `app/<route>/layout.tsx` - layout (only if sibling routes have layouts)
- `app/<route>/loading.tsx` - loading skeleton (only if pattern exists)
- `app/<route>/error.tsx` - error boundary (only if pattern exists)
- `app/<route>/not-found.tsx` - 404 handler (only if pattern exists)
- `app/<route>/opengraph-image.tsx` - OG image (only if pattern exists)
- `app/api/<route>/route.ts` - API route handler (if scaffolding an API-backed page)

**Next.js Pages Router Page**:
- `pages/<route>.tsx` or `pages/<route>/index.tsx`
- SSR/SSG data functions matching project pattern (`getServerSideProps`, `getStaticProps`, `getStaticPaths`)

**Remix Route**:
- `app/routes/<route>.tsx` with `loader`, `action`, `meta`, `ErrorBoundary` matching project patterns

#### 3.2 Vue Component

- `ComponentName.vue` - SFC with `<script setup>` (Vue 3) or Options API (Vue 2) per project
- `ComponentName.spec.ts` - test (if pattern exists)
- `ComponentName.stories.ts` - Storybook story (if pattern exists)
- Match Pinia store pattern if state management scaffolded alongside

#### 3.3 Angular Component

- `component-name.component.ts` - component class
- `component-name.component.html` - template
- `component-name.component.scss` - styles (match preprocessor)
- `component-name.component.spec.ts` - test
- If not standalone: update the parent module's `declarations` array
- If standalone: ensure correct `imports` array in the component

#### 3.4 Svelte Component

- `ComponentName.svelte` - component file
- `ComponentName.test.ts` - test (if pattern exists)
- SvelteKit specifics: `+page.svelte`, `+page.ts`/`+page.server.ts`, `+layout.svelte`, `+error.svelte`

#### 3.5 API Route / Controller

- Route handler with CRUD operations matching existing API patterns
- Input validation using the project's validation library (Zod schema, Joi schema, class-validator decorators, Pydantic model, Django serializer, Laravel FormRequest)
- Error handling matching project patterns (error classes, HTTP status codes, error response format)
- Types/interfaces for request body, query params, path params, and response
- Pagination pattern (cursor-based vs offset-based) matching existing endpoints
- Authentication/authorization middleware matching project pattern
- Rate limiting if other routes use it
- OpenAPI/Swagger decorators if project uses them
- Test file with at least: success case, validation error, not-found, unauthorized

#### 3.6 GraphQL Resolver / Mutation / Subscription

Detect the GraphQL approach:

- **Schema-first** (Apollo Server with `.graphql` files, Mercurius):
  - Type definition in `.graphql` schema file
  - Resolver function in resolver map
  - Update schema stitching/merging if the project composes schemas
- **Code-first** (Pothos, Nexus, TypeGraphQL, NestJS GraphQL):
  - Type/Object builder definitions
  - Query/Mutation/Subscription field definitions
  - Input types for mutations
  - Resolver class with decorated methods (TypeGraphQL/NestJS)
- Generate DataLoader definitions if the project uses DataLoader for N+1 prevention
- Include connection/edge types for pagination if the project uses Relay-style pagination
- Add to schema composition (stitching, federation, or merge) if applicable

#### 3.7 tRPC Router

- Router definition with procedures (query, mutation, subscription)
- Input validation schemas (Zod, typically)
- Output types
- Middleware chains matching existing routers
- Add router to the app router merge
- Generate client-side hook usage example as a comment

#### 3.8 Service / Module

- Service class/function module matching project pattern
- Interface/abstract class if the project uses dependency injection or programming to interfaces
- Constructor injection or functional dependency pattern matching project style
- Unit test with mocked dependencies
- Registration in DI container if applicable (NestJS module providers, Angular services, Spring beans, .NET DI)

#### 3.9 Database Model / Entity + Migration

Detect ORM and generate accordingly:

- **Prisma**: Add model to `schema.prisma`, generate migration with `npx prisma migrate dev`
- **Drizzle**: Schema definition in the appropriate schema file, migration SQL
- **TypeORM**: Entity class with decorators, auto-generated migration
- **Sequelize**: Model definition, migration file with `up`/`down`
- **MikroORM**: Entity class, migration
- **Django ORM**: Model class in `models.py`, run `makemigrations`
- **SQLAlchemy**: Model class, Alembic migration
- **ActiveRecord**: Model class, migration file with `change` method
- **Entity Framework**: Entity class, DbContext update, migration
- **GORM**: Struct with tags, migration
- **Knex/Kysely**: Migration file with schema builder

Include:
- Proper field types, nullability, defaults, indexes
- Relationships/associations matching existing model patterns
- Timestamps (`created_at`, `updated_at`) if other models have them
- Soft delete (`deleted_at`) if the project uses soft deletes
- Factory/fixture/seeder for testing data

#### 3.10 Middleware Chain

- Middleware function matching framework pattern:
  - **Express/Fastify**: `(req, res, next)` or Fastify hook pattern
  - **NestJS**: `NestMiddleware` class or functional middleware, guard, or interceptor
  - **Django**: Middleware class with `__call__`, `process_request`, `process_response`
  - **FastAPI**: `@app.middleware("http")` or Starlette `BaseHTTPMiddleware`
  - **Rails**: Rack middleware
  - **ASP.NET**: Middleware class with `InvokeAsync`
  - **Laravel**: Middleware class with `handle` method
- Registration in the middleware pipeline/chain
- Test covering both pass-through and short-circuit cases
- Proper ordering consideration (document where in the chain it should run)

#### 3.11 Background Job / Worker

- Job/worker class matching project's job framework:
  - **BullMQ / Bull**: Job processor + queue definition + job data type
  - **Celery**: Task function with decorators, task registration
  - **Sidekiq**: Worker class with `perform` method
  - **Dramatiq**: Actor with decorators
  - **Laravel Queue**: Job class with `handle` method
  - **Hangfire / .NET Background Service**: `IHostedService` or Hangfire job class
  - **Temporal / Inngest / Trigger.dev**: Workflow/function definition
  - **Go**: Worker goroutine pattern matching project
- Queue configuration (name, concurrency, retry policy, dead-letter)
- Retry strategy (exponential backoff, max attempts) matching other jobs
- Error handling and failure notification
- Test with job execution assertions
- Scheduled/cron trigger if applicable (add to scheduler config)

#### 3.12 WebSocket Handler

- WebSocket handler matching project pattern:
  - **Socket.io**: Event handler with typed events
  - **ws / native WebSocket**: Connection handler, message parser
  - **NestJS Gateway**: `@WebSocketGateway` with `@SubscribeMessage` handlers
  - **Phoenix Channels**: Channel module with `join`, `handle_in`
  - **Django Channels**: Consumer class with `connect`, `receive`, `disconnect`
  - **FastAPI WebSocket**: WebSocket route handler
  - **Action Cable**: Channel class
  - **SignalR**: Hub class
- Event type definitions (inbound and outbound)
- Connection lifecycle (connect, disconnect, reconnect, heartbeat)
- Room/channel management if applicable
- Authentication/authorization on connection
- Test with mock WebSocket connections

#### 3.13 CLI Command

- Command definition matching project's CLI framework:
  - **Commander.js / Yargs / Oclif / Clipanion**: Command class or function
  - **Click / Typer / argparse**: Command function with decorators or parser
  - **Thor**: Command class (Ruby)
  - **Cobra**: Command struct (Go)
  - **Clap**: Command struct with derive macros (Rust)
  - **System.CommandLine**: Command class (.NET)
- Argument and option definitions with types, defaults, and descriptions
- Help text and usage examples
- Input validation and error messages
- Registration in the CLI entry point / command registry
- Test with argument parsing and execution assertions

#### 3.14 Plugin / Extension

- Plugin scaffold matching host application's extension system:
  - Manifest/package file (name, version, entry point, permissions)
  - Main plugin class/module implementing the plugin interface
  - Hook implementations for extension points
  - Configuration schema with defaults
  - Activation/deactivation lifecycle
- If no plugin system exists, scaffold a basic one: interface definition + registration + discovery

#### 3.15 Microservice

- Service entry point with configuration loading
- Health check endpoint (`/health`, `/healthz`, `/readiness`)
- Graceful shutdown handling
- Logging setup matching organization standards
- Environment configuration with validation
- Dockerfile (multi-stage build if project uses Docker)
- `docker-compose.yml` service entry (if project uses docker-compose)
- Messaging contracts:
  - Event schemas (published and consumed)
  - API contracts (OpenAPI spec or protobuf definitions if project uses gRPC)
- Service client/SDK for consumers (if project generates clients)
- Basic integration test scaffold

---

### Step 3b: Custom Templates

If the user has configured `templateDir` in `_config.json` or the project contains a recognized template directory:

1. Check for templates in this order:
   - `${CLAUDE_SKILL_DIR}/templates/<type>/` (skill-local templates)
   - `${templateDir}/<type>/` (user-configured template directory)
   - `.scaffold/templates/<type>/` (project-local templates)
   - `plop-templates/<type>/` (Plop templates)
   - `_templates/<type>/` (Hygen templates)
2. If a template is found, use it as the base and fill in variables:
   - `{{name}}`, `{{Name}}`, `{{NAME}}`, `{{name_plural}}`, `{{name_snake}}`, `{{name_kebab}}`, `{{name_camel}}`, `{{name_pascal}}`
   - `{{date}}`, `{{timestamp}}`, `{{author}}`
   - Conditional sections: `{{#if hasTests}}...{{/if}}`, `{{#if usesTypeScript}}...{{/if}}`
   - Iterators: `{{#each fields}}...{{/each}}` for model fields
3. Support both Handlebars (`.hbs`) and EJS (`.ejs`) template syntax
4. If no templates are found, fall back to pattern detection from existing code (the default behavior)

### Step 4: Smart Wiring

After generating files, automatically wire them into the project so they are immediately functional. Every wiring action must follow patterns found in existing code - never add a registration mechanism that does not already exist in the project.

#### 4a. Barrel Exports

If the project uses barrel exports (`index.ts` files that re-export):
- Add export to the nearest `index.ts`
- If the barrel file does not exist but sibling directories have them, create one
- Match the re-export style: `export { Foo } from './Foo'` vs `export { default as Foo } from './Foo'` vs `export * from './Foo'`

#### 4b. Route Registration

- **Express**: Add `router.use('/path', newRouter)` to the routes file or `app.use()` in the entry point
- **Fastify**: Register the plugin/route in the appropriate scope
- **NestJS**: Add controller to module's `controllers` array, add module to parent module's `imports`
- **Next.js App Router**: No wiring needed (file-system routing), but add to middleware matchers if auth is required
- **Next.js Pages Router**: No wiring needed, but update `_app.tsx` layout if needed
- **Django**: Add `path()` to `urlpatterns` in the appropriate `urls.py`, add app to `INSTALLED_APPS` if new app
- **FastAPI**: Add `app.include_router(router)` with prefix and tags
- **Rails**: Add `resources :name` or custom route to `config/routes.rb`
- **Spring Boot**: Component scanning handles it, but verify package is scanned
- **Laravel**: Add route to `routes/web.php` or `routes/api.php`
- **Go (Chi/Gin/Echo)**: Add route group/handler registration

#### 4c. Navigation Configuration

If creating a page or route that should appear in navigation:
- Detect navigation config files (sidebar config, nav arrays, menu definitions, breadcrumb configs)
- Add entry matching existing nav item structure (label, path, icon, permissions)
- Preserve alphabetical or logical ordering

#### 4d. Dependency Injection

- **NestJS**: Add to `providers` array in the module, export if needed by other modules
- **Angular**: Add to `providers` in module or use `providedIn: 'root'` matching project pattern
- **Spring Boot**: Ensure `@Service`/`@Component`/`@Repository` annotation is present
- **.NET**: Add to `IServiceCollection` in `Program.cs` or `Startup.cs`
- **Laravel**: Add binding in `AppServiceProvider` or create a dedicated service provider
- **Python (dependency-injector)**: Add to the container definition

#### 4e. Module Declarations

- **NestJS**: Create/update module file with proper imports, controllers, providers, exports
- **Angular**: Add to `declarations` and/or `imports` in NgModule (or ensure standalone component imports are correct)
- **Django**: Add app config to `INSTALLED_APPS`, register admin if model scaffolded
- **Rails**: No module declaration needed typically, but add to autoload paths if non-standard location
- **Spring Boot**: Ensure component scan covers the package

#### 4f. GraphQL Schema Wiring

- **Schema-first**: Extend the schema SDL file, add resolver to the resolver map/merge
- **Code-first**: Add builder/type to schema composition (Pothos plugin, Nexus `makeSchema`, TypeGraphQL `buildSchema`)
- **Schema stitching / Federation**: Add to the service's schema, update gateway config if applicable
- Update `codegen.yml` / `codegen.ts` if the project uses GraphQL Code Generator

#### 4g. tRPC Wiring

- Add new router to the `appRouter` merge in the root router file
- Export the router type for client inference

#### 4h. Background Job Registration

- Register the queue/worker in the job system's configuration
- Add to the worker entry point or process manager
- Update Procfile, Docker Compose, or supervisor config if applicable

#### 4i. Type and Schema Updates

- If the project has a centralized types file, add new types there
- If using OpenAPI, add endpoint to the spec
- If using GraphQL codegen, note that codegen should be re-run
- If using Prisma, remind to run `npx prisma generate` after schema changes

### Step 5: Convention Enforcement (Final Check)

Before writing any file, run these validations:

1. **Naming convention compliance**: Every generated identifier (file, class, function, variable, type) must match the convention detected in Step 1c. Log any auto-corrections.
2. **File location compliance**: Every generated file must be in the correct directory per the architecture pattern detected in Step 1b.
3. **Import ordering**: When modifying existing files (barrel exports, route registrations, module declarations), maintain the established import ordering:
   - External packages first
   - Internal aliases second (`@/`, `~/`)
   - Relative imports last
   - Type-only imports grouped per project convention
   - Alphabetical within groups if the project follows that pattern
4. **Consistent formatting**: Match the project's formatting (indentation, quotes, semicolons, trailing commas). If Prettier/ESLint/Biome config exists, follow it.
5. **No orphaned files**: Every generated file must be reachable - imported, registered, or routed to from somewhere.

### Step 6: Report

**Template:** `templates/scaffold-report.md`
Output report template summarizing detected patterns, created files, wiring changes, convention notes, and next steps.

---

## Framework-Specific Full-Stack Scaffolds

When `type` is `feature`, generate the full vertical slice for the detected framework. Below are the complete file sets per framework.

### Next.js (App Router) Feature

| File | Purpose |
|---|---|
| `app/(group)/<route>/page.tsx` | Page component with data fetching |
| `app/(group)/<route>/layout.tsx` | Layout (if feature needs its own) |
| `app/(group)/<route>/loading.tsx` | Loading skeleton |
| `app/(group)/<route>/error.tsx` | Error boundary |
| `app/api/<route>/route.ts` | API route with GET/POST/PUT/DELETE |
| `src/components/<feature>/<Name>.tsx` | Reusable UI component |
| `src/components/<feature>/<Name>.test.tsx` | Component test |
| `src/lib/api/<feature>.ts` | API client functions |
| `src/lib/validations/<feature>.ts` | Zod schemas |
| `src/types/<feature>.ts` | TypeScript type definitions |
| `prisma/migrations/...` | Database migration (if using Prisma) |

### Django Feature

| File | Purpose |
|---|---|
| `<app>/models.py` | Model definition |
| `<app>/views.py` or `<app>/api/views.py` | View or ViewSet |
| `<app>/serializers.py` | DRF serializer (if using DRF) |
| `<app>/urls.py` | URL configuration |
| `<app>/admin.py` | Admin registration |
| `<app>/tests/test_models.py` | Model tests |
| `<app>/tests/test_views.py` | View/API tests |
| `<app>/filters.py` | DRF filters (if using django-filter) |
| `<app>/permissions.py` | Custom permissions (if needed) |
| `<app>/signals.py` | Signals (if pattern exists) |
| `<app>/tasks.py` | Celery tasks (if Celery is used) |
| `<app>/migrations/0001_initial.py` | Auto-generated migration |
| `<app>/templates/<app>/<name>.html` | Template (if full-stack, not API-only) |

### Rails Feature

| File | Purpose |
|---|---|
| `app/models/<name>.rb` | ActiveRecord model |
| `app/controllers/<names>_controller.rb` | Controller with actions |
| `app/controllers/api/v1/<names>_controller.rb` | API controller (if API) |
| `app/views/<names>/` | View templates (if full-stack) |
| `app/serializers/<name>_serializer.rb` | Serializer (if using AMS or Blueprinter) |
| `app/services/<name>_service.rb` | Service object (if pattern exists) |
| `app/jobs/<name>_job.rb` | Background job (if needed) |
| `db/migrate/<timestamp>_create_<names>.rb` | Migration |
| `config/routes.rb` | Route addition |
| `spec/models/<name>_spec.rb` | Model spec |
| `spec/requests/<names>_spec.rb` | Request spec |
| `spec/factories/<names>.rb` | FactoryBot factory |

### Spring Boot Feature

| File | Purpose |
|---|---|
| `src/main/java/.../entity/<Name>.java` | JPA entity |
| `src/main/java/.../repository/<Name>Repository.java` | Spring Data repository |
| `src/main/java/.../service/<Name>Service.java` | Service interface |
| `src/main/java/.../service/impl/<Name>ServiceImpl.java` | Service implementation |
| `src/main/java/.../controller/<Name>Controller.java` | REST controller |
| `src/main/java/.../dto/<Name>Request.java` | Request DTO |
| `src/main/java/.../dto/<Name>Response.java` | Response DTO |
| `src/main/java/.../mapper/<Name>Mapper.java` | MapStruct mapper (if used) |
| `src/main/java/.../exception/<Name>NotFoundException.java` | Custom exception |
| `src/main/resources/db/migration/V<n>__create_<name>.sql` | Flyway migration |
| `src/test/java/.../controller/<Name>ControllerTest.java` | Controller test |
| `src/test/java/.../service/<Name>ServiceTest.java` | Service test |
| `src/test/java/.../repository/<Name>RepositoryTest.java` | Repository test |

### Laravel Feature

| File | Purpose |
|---|---|
| `app/Models/<Name>.php` | Eloquent model |
| `app/Http/Controllers/<Name>Controller.php` | Controller |
| `app/Http/Requests/<Name>Request.php` | Form request validation |
| `app/Http/Resources/<Name>Resource.php` | API resource transformer |
| `app/Http/Resources/<Name>Collection.php` | Collection resource |
| `app/Services/<Name>Service.php` | Service class (if pattern exists) |
| `app/Policies/<Name>Policy.php` | Authorization policy |
| `app/Events/<Name>Created.php` | Event (if events pattern exists) |
| `app/Listeners/Handle<Name>Created.php` | Listener (if events used) |
| `app/Jobs/Process<Name>.php` | Queue job (if needed) |
| `database/migrations/<timestamp>_create_<names>_table.php` | Migration |
| `database/factories/<Name>Factory.php` | Factory |
| `database/seeders/<Name>Seeder.php` | Seeder |
| `routes/api.php` | Route addition |
| `tests/Feature/<Name>Test.php` | Feature test |

### FastAPI Feature

| File | Purpose |
|---|---|
| `app/models/<name>.py` | SQLAlchemy/Tortoise model |
| `app/schemas/<name>.py` | Pydantic schemas (create, update, response) |
| `app/routers/<name>.py` | Router with CRUD endpoints |
| `app/services/<name>.py` | Business logic service |
| `app/repositories/<name>.py` | Data access layer (if pattern exists) |
| `app/dependencies/<name>.py` | Dependency injection functions |
| `alembic/versions/<hash>_create_<name>.py` | Alembic migration |
| `tests/test_<name>.py` | API + unit tests |

### NestJS Feature

| File | Purpose |
|---|---|
| `src/<feature>/<feature>.module.ts` | Feature module |
| `src/<feature>/<feature>.controller.ts` | Controller with endpoints |
| `src/<feature>/<feature>.service.ts` | Service with business logic |
| `src/<feature>/<feature>.entity.ts` | TypeORM/Prisma entity |
| `src/<feature>/dto/create-<feature>.dto.ts` | Create DTO |
| `src/<feature>/dto/update-<feature>.dto.ts` | Update DTO |
| `src/<feature>/<feature>.controller.spec.ts` | Controller test |
| `src/<feature>/<feature>.service.spec.ts` | Service test |
| `src/<feature>/<feature>.e2e-spec.ts` | E2E test (if pattern exists) |
| `src/app.module.ts` | Updated with new module import |

---

## Configuration

Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:

**Template:** `templates/default-config.json`
Default configuration schema with all supported options including test/style/story toggles, naming convention overrides, and auto-wiring preferences.

All settings are optional. When not set, behavior is auto-detected from the project. Explicit settings override auto-detection.
