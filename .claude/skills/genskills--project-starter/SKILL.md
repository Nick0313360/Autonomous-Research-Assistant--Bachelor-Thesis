---
name: genskills:project-starter
description: >
  Create new projects from template starter kits for any language/framework.
  Triggers on: "create project", "new project", "init project", "starter kit",
  "project template", "bootstrap project", "start new app".
user-invocable: true
argument-hint: "[framework] [project-name] - e.g., 'nextjs my-app' or 'fastapi backend-service'"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(npm *), Bash(npx *), Bash(yarn *), Bash(pnpm *), Bash(pip *), Bash(python *), Bash(cargo *), Bash(go *), Bash(dotnet *), Bash(flutter *), Bash(composer *), Bash(git *), Bash(mkdir *), Bash(cd *), Bash(mv *)"
genskills-version: "1.4.2"
genskills-category: "development"
genskills-depends: ["genskills:env-setup"]
---

# Project Starter

Create new projects from template starter kits with best-practice structure, tooling, security, observability, testing, and CI/CD for any language or framework. Projects are production-grade from commit zero.

## Process

### Step 0: Load Context
- Check for `CLAUDE.md` at the project root - follow any organizational conventions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Note the current working directory - projects will be created here unless specified otherwise

### Step 1: Parse Arguments
Parse `$ARGUMENTS`:
- `$0` = framework/language identifier (see Supported Starters below)
- `$1` = project name (kebab-case recommended)
- Additional flags:
  - `--typescript` - force TypeScript (default for JS projects)
  - `--no-git` - skip git initialization
  - `--minimal` - bare-bones scaffold, skip enhancements
  - `--monorepo` - set up workspace with Turborepo/Nx
  - `--docker` - include Dockerfile and docker-compose
  - `--ci` - include CI/CD pipeline
  - `--arch <pattern>` - architecture preset (see Architecture Presets)
  - `--auth <provider>` - include authentication scaffold
  - `--db <orm>` - include database integration
  - `--deploy <target>` - include deployment configuration
  - `--observability` - include logging, tracing, health checks
  - `--security` - include security hardening
  - `--full` - equivalent to `--docker --ci --observability --security`

If arguments are missing or ambiguous, ask the user:
1. What language/framework?
2. Project name?
3. Any specific needs? (TypeScript, Docker, CI/CD, monorepo, architecture pattern, auth, database)

### Step 2: Select Starter Template
Match the framework identifier to one of the supported starters below. If an official CLI tool exists, prefer using it. Otherwise, generate the project structure manually from templates.

#### Supported Starters

**JavaScript / TypeScript**
| Identifier | Tool | Command |
|---|---|---|
| `nextjs` | create-next-app | `npx create-next-app@latest <name> --typescript --tailwind --eslint --app --src-dir` |
| `react` | Vite | `npm create vite@latest <name> -- --template react-ts` |
| `vue` | create-vue | `npm create vue@latest <name>` |
| `svelte` | sv | `npx sv create <name>` |
| `express` | manual | Generate Express + TypeScript starter |
| `nestjs` | Nest CLI | `npx @nestjs/cli new <name>` |
| `nuxt` | nuxi | `npx nuxi@latest init <name>` |
| `astro` | create-astro | `npm create astro@latest -- <name>` |
| `remix` | create-remix | `npx create-remix@latest <name>` |
| `electron` | manual | Generate Electron + Vite starter |
| `node` | manual | Generate Node.js + TypeScript starter |
| `bun` | bun init | `bun init <name>` |

**Python**
| Identifier | Tool | Command |
|---|---|---|
| `fastapi` | manual | Generate FastAPI project with uvicorn, pydantic |
| `django` | django-admin | `django-admin startproject <name>` |
| `flask` | manual | Generate Flask project with blueprints |
| `python` | manual | Generate Python package with pyproject.toml |
| `streamlit` | manual | Generate Streamlit app structure |

**Rust**
| Identifier | Tool | Command |
|---|---|---|
| `rust` | cargo | `cargo new <name>` |
| `rust-lib` | cargo | `cargo new <name> --lib` |
| `axum` | manual | Generate Axum web service starter |
| `tauri` | create-tauri-app | `npm create tauri-app@latest <name>` |

**Go**
| Identifier | Tool | Command |
|---|---|---|
| `go` | go mod | `mkdir <name> && cd <name> && go mod init <module>` |
| `go-api` | manual | Generate Go REST API with chi/gin |
| `go-cli` | manual | Generate Go CLI with cobra |

**Mobile**
| Identifier | Tool | Command |
|---|---|---|
| `react-native` | expo | `npx create-expo-app@latest <name>` |
| `flutter` | flutter | `flutter create <name>` |
| `kotlin` | manual | Generate Kotlin/Android project |
| `swift` | manual | Generate Swift/iOS package |

**Other**
| Identifier | Tool | Command |
|---|---|---|
| `dotnet` | dotnet | `dotnet new webapi -n <name>` |
| `spring` | manual | Generate Spring Boot with Gradle/Maven |
| `laravel` | composer | `composer create-project laravel/laravel <name>` |
| `phoenix` | mix | `mix phx.new <name>` |
| `rails` | rails | `rails new <name>` |

#### Advanced Project Types

| Identifier | Description | Scaffold Details |
|---|---|---|
| `monorepo-turbo` | Turborepo monorepo | `apps/` + `packages/` workspace with shared tsconfig, eslint, UI package |
| `monorepo-nx` | Nx workspace | Nx-managed workspace with apps and libs directories |
| `chrome-ext` | Chrome extension | Manifest V3, popup, background service worker, content script, options page |
| `firefox-ext` | Firefox extension | WebExtension manifest, popup, background, content scripts |
| `vscode-ext` | VS Code extension | Extension scaffold with commands, activation events, package.json contribution points |
| `slack-bot` | Slack bot | Bolt.js framework, event subscriptions, slash commands, interactive messages |
| `discord-bot` | Discord bot | Discord.js with slash commands, event handlers, command registry |
| `cli` | CLI tool | Node: commander + chalk + ora; Rust: clap + colored; Go: cobra + viper; Python: click + rich |
| `sdk` | SDK / library | Dual CJS/ESM build (tsup), type declarations, API surface, changelog, semantic versioning |
| `design-system` | Component library | Storybook 8, React/Vue components, tokens, Chromatic visual testing, npm publish config |

### Step 3: Architecture Presets

When `--arch <pattern>` is specified, overlay the chosen architecture onto the project structure. These presets define directory layout, module boundaries, and dependency rules.

#### Clean Architecture

**Template:** `templates/arch-clean.txt`
Directory layout with domain, application, infrastructure, and presentation layers plus test directories.
- Dependency rule: domain has zero imports from outer layers
- Generate barrel exports (`index.ts`) for each layer
- Include a DI container (tsyringe / InversifyJS / Python dependency-injector)

#### Hexagonal / Ports-and-Adapters

**Template:** `templates/arch-hexagonal.txt`
Directory layout with core (domain + ports), inbound/outbound adapters, and config wiring.

#### Domain-Driven Design (DDD)

**Template:** `templates/arch-ddd.txt`
Directory layout with shared kernel, bounded contexts (domain/application/infrastructure per context), and anti-corruption layer.
- Include domain event bus (in-process for monolith, message broker for distributed)
- Generate aggregate root base class with event sourcing hooks
- Include repository pattern with unit-of-work

#### CQRS (Command Query Responsibility Segregation)

**Template:** `templates/arch-cqrs.txt`
Directory layout with separated command (write) and query (read) sides, event store, and bus infrastructure.
- Include command bus and query bus implementations
- Generate mediator pattern (MediatR-style for .NET, custom for Node/Python)

#### Event-Driven Architecture

**Template:** `templates/arch-event-driven.txt`
Directory layout with producers, consumers, event schemas, sagas, projections, and broker infrastructure.
- Include dead-letter queue handling and retry policies
- Generate idempotency middleware for consumers
- Include schema evolution strategy documentation

#### Serverless

**Template:** `templates/arch-serverless.txt`
Directory layout with per-function directories, shared utilities, and IaC infrastructure definitions.
- AWS Lambda: SAM/CDK template, API Gateway config, Lambda layers
- Vercel Functions: `vercel.json` with rewrites, edge config
- Cloudflare Workers: `wrangler.toml`, D1/KV bindings, Durable Objects scaffold

### Step 4: Create the Project

**If official CLI exists:**
1. Run the CLI command from the table above
2. Navigate into the project directory
3. Proceed to Step 5 for enhancements

**If manual generation (no CLI or `--minimal` flag):**
Generate the project structure following language-specific templates below.

#### Manual Template: Express + TypeScript

**Template:** `templates/manual-express-typescript.txt`
Full project structure with routes, controllers, middleware, services, types, and test directories.

#### Manual Template: FastAPI

**Template:** `templates/manual-fastapi.txt`
Full project structure with versioned API, core config, models, schemas, services, tests, and Alembic migrations.

#### Manual Template: Node.js + TypeScript

**Template:** `templates/manual-node-typescript.txt`
Minimal project structure with src, tests, tsconfig, and ESLint config.

#### Manual Template: Go REST API

**Template:** `templates/manual-go-rest-api.txt`
Standard Go project layout with cmd, internal (handlers/middleware/model/service/repository), and pkg directories.

#### Manual Template: Rust Axum

**Template:** `templates/manual-rust-axum.txt`
Project structure with routes, handlers, custom extractors, error types, and tests.

#### Manual Template: Python Package

**Template:** `templates/manual-python-package.txt`
PEP 561-compliant package layout with src, tests, pyproject.toml, and license.

#### Manual Template: Monorepo (Turborepo)

**Template:** `templates/manual-monorepo-turborepo.txt`
Workspace layout with apps, shared packages (UI, config, shared utils), turbo.json, and pnpm workspace config.

#### Manual Template: Chrome Extension (Manifest V3)

**Template:** `templates/manual-chrome-extension.txt`
Manifest V3 structure with background service worker, content script, popup, options page, and shared utilities.

#### Manual Template: CLI Tool (Node.js)

**Template:** `templates/manual-cli-tool-node.txt`
CLI project with commands, config loading (cosmiconfig), logger, prompts, bin entry, and tests.

#### Manual Template: SDK / Library (Dual CJS/ESM)

**Template:** `templates/manual-sdk-library.txt`
Library structure with barrel exports, client class, types, tsup dual build config, and changelog.

### Step 5: Enhance (based on flags and preferences)

**Always do:**
- Initialize git repo (unless `--no-git`): `git init && git add . && git commit -m "Initial commit"`
- Create `.gitignore` appropriate for the language (if not already created by CLI)
- Create `.env.example` if the project uses environment variables
- Ensure a README.md exists with: project name, description, quickstart, and available scripts

---

#### Security-First Setup (`--security` or `--full`)

Apply all applicable items based on the project type:

**HTTP Security Headers**
- Install and configure `helmet` (Express), `secure-headers` (FastAPI), or equivalent
- Generate Content Security Policy (CSP) configuration:
  **Template:** `templates/csp-config.ts`
  CSP directives with self, strict-dynamic, and OWASP-recommended defaults.
- Set OWASP recommended headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`

**CORS Configuration**
- Generate a CORS configuration module with explicit origin allowlist:
  ```js
  // cors.config.ts
  export const corsOptions = {
    origin: process.env.ALLOWED_ORIGINS?.split(',') || ['http://localhost:3000'],
    credentials: true,
    methods: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH'],
    allowedHeaders: ['Content-Type', 'Authorization', 'X-Request-ID'],
    maxAge: 86400,
  };
  ```

**Rate Limiting**
- Install and configure rate limiter (express-rate-limit, slowapi, or equivalent)
- Default: 100 requests/15 minutes per IP for API routes, stricter for auth endpoints
- Include separate rate limit tiers: public, authenticated, admin

**Input Sanitization**
- Install validation library (zod, joi, pydantic, or equivalent)
- Generate validation middleware that sanitizes all user input
- Include example request validation schema

**Dependency Auditing**
- Add `npm audit` / `pip-audit` / `cargo audit` step in CI
- Generate `.npmrc` or equivalent with `audit=true`
- Add `package-lock.json` or lockfile to version control

---

#### Observability Built-In (`--observability` or `--full`)

**Structured Logging**
- Node.js: install and configure `pino` with `pino-pretty` for development
  **Template:** `templates/logger-pino.ts`
  Pino logger with env-based log level, pretty printing in dev, service metadata, and sensitive field redaction.
- Python: configure `structlog` with JSON output for production, console for development
- Go: configure `slog` or `zerolog` with structured JSON output
- Rust: configure `tracing` + `tracing-subscriber` with JSON formatting
- Include request ID propagation in all log entries
- Redact sensitive fields (authorization headers, cookies, passwords)

**OpenTelemetry Instrumentation**
- Install OpenTelemetry SDK and auto-instrumentation packages
- Generate a tracing configuration module:
  ```js
  // tracing.ts - loaded before app starts
  import { NodeSDK } from '@opentelemetry/sdk-node';
  import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
  import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
  ```
- Include environment variables in `.env.example`:
  ```
  OTEL_SERVICE_NAME=<name>
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
  OTEL_LOG_LEVEL=info
  ```
- Add docker-compose service for Jaeger/Zipkin for local development

**Health Check Endpoints**
- Generate `/health` (liveness) and `/ready` (readiness) endpoints
- Liveness: returns 200 if process is running
- Readiness: checks database connectivity, cache connectivity, and external service dependencies
- Include structured response:
  **Template:** `templates/health-check-response.json`
  Health check JSON with status, version, uptime, and per-dependency checks with latency.

**Graceful Shutdown**
- Handle `SIGTERM` and `SIGINT` signals
- Drain in-flight requests before shutting down
- Close database connections, flush log buffers, stop accepting new requests
- Include configurable shutdown timeout (default: 30 seconds)

**Error Tracking (Sentry)**
- Install Sentry SDK for the target platform
- Generate initialization module with environment-based DSN
- Configure source map uploads in production build
- Include Sentry environment variables in `.env.example`:
  ```
  SENTRY_DSN=
  SENTRY_ENVIRONMENT=development
  SENTRY_TRACES_SAMPLE_RATE=0.1
  ```

---

#### Database Integration (`--db <orm>`)

Select and configure the specified ORM/database layer:

**Prisma (Node.js)**
- Install `prisma` and `@prisma/client`
- Generate initial `prisma/schema.prisma` with a User model example
- Configure datasource for PostgreSQL (configurable via env)
- Create `prisma/seed.ts` with sample data insertion
- Add scripts: `db:migrate`, `db:push`, `db:seed`, `db:studio`
- Include connection pooling via Prisma Accelerate or PgBouncer notes

**Drizzle (Node.js)**
- Install `drizzle-orm` and `drizzle-kit`
- Generate `drizzle.config.ts` and initial schema in `src/db/schema.ts`
- Create migration directory structure with `drizzle-kit generate`
- Include seed script and connection setup

**TypeORM (Node.js)**
- Install `typeorm` and database driver
- Generate `data-source.ts` configuration
- Create initial entity, migration directory, and seed script
- Include migration scripts in package.json

**SQLAlchemy / Alembic (Python)**
- Configure SQLAlchemy with async support
- Set up Alembic for migrations with `alembic init`
- Generate initial model, migration, and seed script
- Include connection pooling configuration

**GORM (Go)**
- Install `gorm.io/gorm` and driver
- Generate model, repository, and migration setup
- Include connection pooling and health check integration

**Redis Cache Layer (all platforms)**
- Install Redis client (ioredis, redis-py, go-redis)
- Generate cache service with get/set/invalidate methods
- Include TTL configuration and cache key namespacing
- Add Redis to docker-compose.yml
- Include connection pool settings and reconnection logic

---

#### Authentication Starters (`--auth <provider>`)

**NextAuth.js / Auth.js**
- Install `next-auth` or `@auth/core`
- Generate `auth.ts` configuration with providers array
- Include Google, GitHub, and Credentials provider examples
- Set up session callback, JWT callback, and sign-in page
- Add auth environment variables to `.env.example`:
  ```
  NEXTAUTH_URL=http://localhost:3000
  NEXTAUTH_SECRET=<generate-random>
  GOOGLE_CLIENT_ID=
  GOOGLE_CLIENT_SECRET=
  GITHUB_CLIENT_ID=
  GITHUB_CLIENT_SECRET=
  ```

**Passport.js (Express)**
- Install `passport` with selected strategies
- Generate passport configuration module, serialization/deserialization
- Include local strategy with bcrypt password hashing
- Include JWT strategy for API authentication
- Generate auth middleware for route protection

**JWT Middleware (generic)**
- Generate JWT utility module (sign, verify, refresh)
- Include access token + refresh token pattern
- Configure token expiry (15 min access, 7 day refresh)
- Generate auth middleware that validates and decodes JWT
- Include token blacklist strategy for logout

**OAuth2 Setup**
- Generate OAuth2 flow with PKCE for public clients
- Include authorization URL builder, token exchange, and refresh logic
- Generate callback handler with state parameter validation
- Support multiple providers via configuration

**Session Management**
- Configure session store (Redis-backed for production, memory for development)
- Include secure cookie configuration (httpOnly, secure, sameSite)
- Generate session middleware with rolling window expiry
- Include CSRF protection setup

**RBAC / Permissions Scaffold**
- Generate role and permission models/types
- Create authorization middleware that checks roles/permissions
- Include role hierarchy (admin > editor > viewer)
- Generate permission-checking decorators/middleware:
  ```ts
  // Usage: @RequirePermission('posts:write')
  // Usage: requireRole('admin')(req, res, next)
  ```
- Include seed data for default roles and permissions

---

#### Testing Infrastructure

**Always include (unless `--minimal`):**
- Test framework configured and ready:
  - Node.js: Vitest (preferred) or Jest with TypeScript support
  - Python: pytest with pytest-asyncio, pytest-cov
  - Rust: built-in `cargo test` with rstest for parameterized tests
  - Go: built-in `go test` with testify assertions
- At least one passing test (health endpoint test)
- Test scripts in package.json / Makefile / pyproject.toml

**Unit Test Setup**
- Configure test runner with path aliases matching tsconfig/pyproject
- Generate test utilities module (factories, fixtures, mocks)
- Include example test demonstrating mocking patterns for the framework
- Configure coverage collection with thresholds:
  **Template:** `templates/coverage-thresholds.json`
  Coverage thresholds: 80% statements/functions/lines, 75% branches.

**Integration Test Setup**
- Generate test setup that starts/stops services (database, cache)
- Include test database configuration (separate from development)
- Generate Docker Compose file for test dependencies: `docker-compose.test.yml`
- Include database cleanup between tests (transaction rollback or truncate)
- Generate example integration test for a database-backed endpoint

**E2E Test Framework**
- If web project, set up Playwright (preferred) or Cypress:
  - Install and configure with TypeScript support
  - Generate first test: navigate to homepage, assert title/content
  - Include test configuration for multiple browsers
  - Generate page object model example
  - Include CI-compatible configuration (headless, retry, screenshot on failure)
  **Template:** `templates/e2e-test-structure.txt`
  E2E test directory with page objects, auth fixtures, specs, and Playwright config.

**Test Database Setup**
- Generate script to create and seed test database
- Include teardown script for CI cleanup
- Configure separate `.env.test` with test database connection string
- Include test data factories/builders for common models

---

#### Advanced CI/CD Templates (`--ci` or `--full`)

Generate `.github/workflows/ci.yml` with a multi-stage pipeline:

**Template:** `templates/ci-pipeline.yml`
Full GitHub Actions workflow with lint, test (matrix), security (CodeQL + audit), build, e2e (Playwright), deploy-preview, deploy-production, and semantic-release jobs.

Adapt the pipeline for the specific language:
- **Python**: Replace with `pip install`, `pytest`, `ruff`, `mypy`, matrix over Python 3.10/3.11/3.12
- **Go**: Replace with `go vet`, `golangci-lint`, `go test -race -coverprofile`, matrix over Go 1.21/1.22
- **Rust**: Replace with `cargo fmt --check`, `cargo clippy`, `cargo test`, `cargo audit`
- **.NET**: Replace with `dotnet restore`, `dotnet build`, `dotnet test`, `dotnet publish`

---

#### Deployment Configs (`--deploy <target>`)

**Vercel**
- Generate `vercel.json` with rewrites, headers, and environment variable references
- Include build and output configuration
- Include preview branch configuration

**Netlify**
- Generate `netlify.toml` with build command, publish directory, redirects, and headers
- Include serverless functions directory configuration

**AWS CDK / Terraform**
- AWS CDK: Generate `infrastructure/` directory with CDK app, stack, and constructs for the chosen service (Lambda, ECS, EC2)
- Terraform: Generate `terraform/` directory with `main.tf`, `variables.tf`, `outputs.tf`, state backend config
- Include environment-specific configurations (dev, staging, production)

**Kubernetes**
- Generate `k8s/` directory:
  **Template:** `templates/k8s-structure.txt`
  Kustomize-based layout with base (deployment, service, configmap, HPA) and dev/production overlays.
- Include liveness and readiness probes matching `/health` and `/ready` endpoints
- Include resource requests and limits
- Include Kustomize overlays for dev/production

**Railway / Fly.io**
- Railway: Generate `railway.json` or `railway.toml` with build and deploy configuration
- Fly.io: Generate `fly.toml` with app name, build strategy, services, health checks, and scaling config

**PM2 Ecosystem**
- Generate `ecosystem.config.js`:
  **Template:** `templates/pm2-ecosystem.js`
  PM2 cluster mode config with environment-specific settings, memory limits, and log files.

**Docker (always generated with `--docker` or `--full`)**
- Generate multi-stage Dockerfile:
  **Template:** `templates/dockerfile-multistage.dockerfile`
  Three-stage build (deps, build, production) with non-root user, health check, and minimal image.
- Generate `docker-compose.yml` with app, database, and cache services
- Generate `.dockerignore` matching `.gitignore` plus build artifacts
- Include health checks in compose services
- Include volume mounts for development hot-reload

---

#### Developer Experience (always applied unless `--minimal`)

**Husky + lint-staged + commitlint**
- Install and configure `husky` for git hooks
- Configure `lint-staged` in `package.json`:
  ```json
  {
    "lint-staged": {
      "*.{ts,tsx}": ["eslint --fix", "prettier --write"],
      "*.{json,md,yml,yaml}": ["prettier --write"]
    }
  }
  ```
- Install `@commitlint/cli` + `@commitlint/config-conventional`
- Generate `commitlint.config.js` enforcing Conventional Commits
- Set up hooks:
  - `pre-commit`: lint-staged
  - `commit-msg`: commitlint
  - `pre-push`: type-check + test (optional, warn user about speed)

**VS Code Workspace Settings**
- Generate `.vscode/settings.json`:
  **Template:** `templates/vscode-settings.json`
  Editor settings with format-on-save, ESLint auto-fix, TypeScript SDK, and Python/Ruff support.
- Generate `.vscode/extensions.json` with recommended extensions:
  **Template:** `templates/vscode-extensions.json`
  Recommended extensions for Prettier, ESLint, Tailwind, Prisma, Playwright, and Vitest.
- Adjust recommendations based on project type (Python: ruff, pylance; Go: gopls; Rust: rust-analyzer)

**Debug Configurations**
- Generate `.vscode/launch.json` with configurations for:
  - Launch development server with debugger attached
  - Run current test file in debug mode
  - Attach to running Node.js process
  - Docker container remote debugging
  **Template:** `templates/vscode-launch.json`
  Debug configurations for dev server launch and current test file debugging.

**Makefile / Taskfile**
- Generate `Makefile` (or `Taskfile.yml` if user prefers) with common commands:
  **Template:** `templates/makefile.mk`
  Targets for dev, test, test-coverage, test-e2e, lint, format, build, clean, docker, and database operations with self-documenting help.
- Adapt commands for the specific language and toolchain

### Step 6: Install Dependencies
- Run the appropriate install command:
  - JS/TS: `npm install` or `pnpm install` or `yarn install`
  - Python: `pip install -e ".[dev]"` or `pip install -r requirements.txt -r requirements-dev.txt`
  - Rust: `cargo build`
  - Go: `go mod tidy`
  - .NET: `dotnet restore`
- Verify the project builds/runs without errors
- Run linter to confirm zero errors on generated code
- Run test suite to confirm the initial test passes

### Step 7: Report

**Template:** `templates/report-template.md`
Output report format with project summary, structure tree, included features, quick start commands, and next steps.

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `defaultLanguage`: string - default language/framework when not specified (e.g., "nextjs")
- `packageManager`: string - preferred JS package manager: "npm" | "pnpm" | "yarn" | "bun"
- `alwaysTypeScript`: boolean - always use TypeScript for JS projects (default: true)
- `alwaysDocker`: boolean - always include Docker files (default: false)
- `alwaysCI`: boolean - always include CI pipeline (default: false)
- `alwaysSecurity`: boolean - always include security hardening (default: false)
- `alwaysObservability`: boolean - always include observability setup (default: false)
- `defaultArch`: string - default architecture pattern (e.g., "clean", "hexagonal", "ddd")
- `gitInit`: boolean - initialize git repo (default: true)
- `defaultLicense`: string - license to include (default: "MIT")
- `author`: string - author name for package.json / pyproject.toml
- `organization`: string - org prefix for go modules, npm scopes, etc.
- `defaultDb`: string - default database ORM (e.g., "prisma", "drizzle", "sqlalchemy")
- `defaultAuth`: string - default auth provider (e.g., "nextauth", "passport", "jwt")
- `defaultDeploy`: string - default deployment target (e.g., "vercel", "aws-cdk", "k8s")
- `coverageThreshold`: number - minimum test coverage percentage (default: 80)
- `nodeVersions`: string[] - Node.js versions for CI matrix (default: ["18", "20", "22"])
- `pythonVersions`: string[] - Python versions for CI matrix (default: ["3.10", "3.11", "3.12"])
