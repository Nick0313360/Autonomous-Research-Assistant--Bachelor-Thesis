---
name: genskills:docker-gen
description: >
  Generate Dockerfiles, docker-compose.yml, and .dockerignore for any project stack.
  Triggers on: "docker", "dockerfile", "docker-compose", "containerize",
  "dockerize", "add docker".
user-invocable: true
argument-hint: "[target] - e.g., 'production' or 'dev' or 'compose'"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(docker *), Bash(docker-compose *), Bash(npm *), Bash(node *), Bash(python *)"
genskills-version: "1.4.2"
genskills-category: "development"
genskills-depends: []
---

# Docker Gen

Generate production-hardened, multi-environment Docker configurations for any project stack. Outputs are secure by default, optimized for layer caching, and ready for orchestration.

---

## Process

### Step 0: Load Context

- Check for `CLAUDE.md` -- follow any Docker/deployment conventions.
- Check `${CLAUDE_SKILL_DIR}/_config.json` for preferences.
- If a `.env.example` exists, use it to template environment variable references (never copy actual secrets).

### Step 1: Detect Project Stack

- Identify language/framework from `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `pom.xml`, `build.gradle`, `*.csproj`, `Gemfile`, etc.
- Detect package manager (`npm`, `pnpm`, `yarn`, `pip`, `poetry`, `uv`, `cargo`, `go mod`, `maven`, `gradle`).
- Detect asset pipeline (Tailwind, SASS, Webpack, Vite, esbuild) for a dedicated asset compilation stage.
- Identify required services: database, cache, queue, search engine, object storage.
- Check for existing Docker files -- if present, ask before overwriting.
- Note the build command, start command, default port, and any signal-handling requirements (graceful shutdown).
- Detect if the project uses a monorepo layout (workspaces, Nx, Turborepo) and plan build context accordingly.

### Step 2: Parse Arguments

| Argument | Behavior |
|---|---|
| `production` / `prod` | Hardened multi-stage build, Distroless or scratch final image, no dev dependencies. |
| `development` / `dev` | Dev-friendly: hot reload via volume mounts, debug ports exposed, source maps enabled. |
| `staging` | Production build with debug tools retained (curl, sh), verbose logging. |
| `test` | Includes test dependencies, coverage tools, runs test suite as default CMD. |
| `compose` | Generate `docker-compose.yml` with full service graph. |
| `monitoring` | Generate monitoring stack: Prometheus, Grafana, Loki, cAdvisor, Jaeger. |
| `proxy` | Generate reverse-proxy service (Traefik or Nginx) with auto-TLS. |
| `all` or no args | Generate Dockerfile + docker-compose.yml + .dockerignore with all detected services. |

---

### Step 3: Generate Dockerfile

#### 3.1 Base Image Selection

Use specific version tags. Never use `latest`. Prefer minimal base images and choose CVE-free options when available.

| Stack | Dev Base | Production Base | Notes |
|---|---|---|---|
| Node.js / Next.js | `node:<version>-bookworm-slim` | `gcr.io/distroless/nodejs<version>-debian12` | Distroless has no shell -- use debug variant for staging. |
| Python / FastAPI / Django | `python:<version>-slim-bookworm` | `python:<version>-slim-bookworm` (or Distroless Python) | Consider `uv` for faster installs. |
| Go | `golang:<version>-bookworm` | `scratch` or `gcr.io/distroless/static-debian12` | Static binary, no libc needed unless using CGO. |
| Rust | `rust:<version>-bookworm` | `gcr.io/distroless/cc-debian12` or `scratch` | Use `cargo chef` for dependency caching. |
| .NET | `mcr.microsoft.com/dotnet/sdk:<version>` | `mcr.microsoft.com/dotnet/aspnet:<version>-chiseled` | Chiseled = Ubuntu-based Distroless equivalent. |
| Java / Spring | `eclipse-temurin:<version>-jdk` | `eclipse-temurin:<version>-jre-alpine` | Use jlink for custom minimal JRE. |
| Ruby / Rails | `ruby:<version>-slim-bookworm` | `ruby:<version>-slim-bookworm` | Precompile assets in builder stage. |
| PHP / Laravel | `php:<version>-fpm-bookworm` | `php:<version>-fpm-alpine` | Pair with Nginx or Caddy sidecar. |

#### 3.2 Multi-Stage Build Structure

Every Dockerfile must use multi-stage builds. The canonical stage layout:

**Template:** `templates/multi-stage-dockerfile.dockerfile`
Canonical multi-stage Node.js/Next.js Dockerfile with deps, builder, production, development, and test stages.

Use `docker build --target <stage>` to select the environment.

#### 3.3 Dependency Cache Mounts per Ecosystem

Always use BuildKit cache mounts for package manager caches. This avoids re-downloading dependencies on every build.

| Ecosystem | Cache Mount |
|---|---|
| npm | `--mount=type=cache,target=/root/.npm` |
| pnpm | `--mount=type=cache,target=/root/.local/share/pnpm/store` |
| yarn (berry) | `--mount=type=cache,target=/root/.yarn/berry/cache` |
| pip | `--mount=type=cache,target=/root/.cache/pip` |
| uv | `--mount=type=cache,target=/root/.cache/uv` |
| poetry | `--mount=type=cache,target=/root/.cache/pypoetry` |
| cargo | `--mount=type=cache,target=/usr/local/cargo/registry` |
| go | `--mount=type=cache,target=/go/pkg/mod` |
| maven | `--mount=type=cache,target=/root/.m2/repository` |
| gradle | `--mount=type=cache,target=/root/.gradle/caches` |
| composer | `--mount=type=cache,target=/root/.composer/cache` |
| bundler | `--mount=type=cache,target=/usr/local/bundle/cache` |

#### 3.4 Security Hardening (Mandatory for All Production Images)

Every production Dockerfile must include ALL of the following:

**Non-root user setup (per language):**

```dockerfile
# Node (Distroless already provides nonroot user)
USER nonroot:nonroot

# Python / general
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser
USER appuser:appuser

# Go (scratch image -- define numeric UID)
USER 65534:65534

# .NET Chiseled -- already non-root by default
```

**Drop all Linux capabilities:**

```dockerfile
# In docker-compose.yml or docker run:
# --cap-drop=ALL --cap-add=<only-what-you-need>
# In Dockerfile metadata (for documentation):
LABEL org.opencontainers.image.security.capabilities.drop="ALL"
```

**Read-only root filesystem:**

```dockerfile
# Enforced at runtime via docker-compose or orchestrator:
# read_only: true
# tmpfs: ["/tmp", "/var/run"]
```

**No-new-privileges:**

```dockerfile
# Enforced at runtime:
# security_opt: ["no-new-privileges:true"]
```

**Secret management with BuildKit:**

```dockerfile
# Mount secrets at build time -- never COPY secret files into layers
RUN --mount=type=secret,id=npm_token \
    NPM_TOKEN=$(cat /run/secrets/npm_token) npm install

# Build command:
# DOCKER_BUILDKIT=1 docker build --secret id=npm_token,src=./.npm_token .
```

**Vulnerability scanning instruction:**

Always include a comment at the top of the Dockerfile:

```dockerfile
# syntax=docker/dockerfile:1
# Scan: docker scout cves --only-severity critical,high .
# Alt:  trivy image <image-name>
# Alt:  snyk container test <image-name>
```

**HEALTHCHECK instruction:**

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["node", "healthcheck.js"]
# For Distroless (no shell): use a compiled binary or language-native HTTP check
```

#### 3.5 Init Process and Signal Handling (Orchestration Readiness)

Production containers must handle SIGTERM for graceful shutdown. Use an init process for proper PID 1 behavior.

**Template:** `templates/init-process.dockerfile`
Init process options: tini, dumb-init, and Docker's built-in init for proper PID 1 signal handling.

For Go and Rust binaries that already handle signals properly, no init process is needed -- they run as PID 1 directly.

Always implement graceful shutdown in the application code (drain connections, finish in-flight requests, flush logs).

#### 3.6 12-Factor App Compliance

- **Config via environment**: Use `ENV` for defaults, override at runtime. Never bake secrets into images.
- **Stateless processes**: No local file storage for state. Use volumes or external storage.
- **Port binding**: Expose via `EXPOSE` and `PORT` env var.
- **Logs to stdout/stderr**: Never write log files inside the container.
- **Disposability**: Fast startup, graceful shutdown.
- **Dev/prod parity**: Same Dockerfile, different targets.
- **Backing services**: Attached via env vars (DATABASE_URL, REDIS_URL, etc.).

#### 3.7 Multi-Platform Builds

When cross-compilation is needed (e.g., building on ARM Mac for AMD64 deployment):

**Template:** `templates/multi-platform-build.dockerfile`
TARGETARCH-based conditional logic for multi-architecture Docker builds.

For Go:

```dockerfile
ARG TARGETOS TARGETARCH
RUN CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} go build -o /app .
```

---

### Step 4: Generate docker-compose.yml

#### 4.1 Service Profiles

Use profiles to organize services by purpose. Only the services matching active profiles start.

**Template:** `templates/docker-compose-dev.yml`
Full docker-compose.yml with app, PostgreSQL, Redis, migrations, backup, Traefik proxy, and monitoring stack (Prometheus, Grafana, Loki, cAdvisor, Jaeger, OTel Collector).

#### 4.2 Production Compose Override

Generate a `docker-compose.prod.yml` override for production:

**Template:** `templates/docker-compose-prod.yml`
Production compose override with hardened settings: read-only FS, cap-drop ALL, rolling updates, and Docker secrets.

#### 4.3 Database Containers: Deep Configuration

**PostgreSQL custom config (`docker/postgres/postgresql.conf`):**

```
# Performance tuning for containerized PostgreSQL
shared_buffers = '256MB'
effective_cache_size = '768MB'
work_mem = '8MB'
maintenance_work_mem = '128MB'
max_connections = 100
wal_level = replica
max_wal_senders = 3
```

**Initialization scripts (`docker/postgres/init/`):**

```sql
-- 01-extensions.sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- 02-schema.sql
-- Loaded alphabetically. Use numeric prefixes for ordering.
```

**Database restore container:**

**Template:** `templates/db-restore-service.yml`
Compose service definition for restoring a PostgreSQL database from a backup dump file.

**MySQL equivalent:**

**Template:** `templates/mysql-service.yml`
Compose service definition for MySQL 8.4 with custom config, init scripts, and healthcheck.

---

### Step 5: Generate .dockerignore

Use a **whitelist approach** for maximum build context minimization. Start by ignoring everything, then allow only what the build needs.

**Template:** `templates/dockerignore-whitelist.txt`
Whitelist-approach .dockerignore: ignores everything, then selectively allows source, config, and Docker support files.

If the whitelist approach is too restrictive for the detected project structure, fall back to a **blacklist approach** but be thorough:

**Template:** `templates/dockerignore-blacklist.txt`
Blacklist-approach .dockerignore: excludes VCS, dependencies, IDE files, secrets, build artifacts, docs, CI/CD, and test files.

Tailor to the detected stack -- only include entries that are relevant.

---

### Step 6: Build Optimization

#### 6.1 BuildKit Parallel Builds

Enable BuildKit and leverage parallel stage execution:

```bash
# Enable BuildKit
export DOCKER_BUILDKIT=1

# Build with progress output
docker build --progress=plain -t app:latest .

# Build specific target
docker build --target production -t app:prod .
```

#### 6.2 CI/CD Caching Strategies

**GitHub Actions with registry cache:**

```yaml
- uses: docker/build-push-action@v6
  with:
    cache-from: type=registry,ref=ghcr.io/org/app:buildcache
    cache-to: type=registry,ref=ghcr.io/org/app:buildcache,mode=max
```

**GitHub Actions with GitHub Actions cache:**

```yaml
- uses: docker/build-push-action@v6
  with:
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

**Inline cache (simplest, works everywhere):**

```dockerfile
# In Dockerfile:
ARG BUILDKIT_INLINE_CACHE=1

# When building:
docker build --build-arg BUILDKIT_INLINE_CACHE=1 -t app:latest .

# On subsequent builds:
docker build --cache-from app:latest -t app:latest .
```

#### 6.3 Layer Caching Analysis

Validate layer efficiency after building:

```bash
# Inspect layer sizes
docker history <image> --no-trunc

# Analyze image with dive
dive <image>

# Check image size
docker images <image> --format "{{.Size}}"
```

#### 6.4 Multi-Platform Build

```bash
# Create a builder for multi-platform
docker buildx create --name multiplatform --use

# Build and push for multiple architectures
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag ghcr.io/org/app:latest \
  --push .
```

---

### Step 7: Kubernetes Readiness Checklist

When generating for Kubernetes-bound workloads, verify:

- **Signal handling**: Application catches SIGTERM and shuts down within `terminationGracePeriodSeconds` (default 30s).
- **Liveness probe**: Endpoint that returns 200 when the process is alive (e.g., `/healthz`).
- **Readiness probe**: Endpoint that returns 200 when ready to accept traffic (e.g., `/readyz`). Should check downstream dependencies.
- **Startup probe**: For slow-starting apps, prevents premature liveness kills.
- **Non-root UID**: Required by most Pod Security Standards. Use `runAsNonRoot: true` and `runAsUser: 65534` in the security context.
- **Read-only root filesystem**: Use `readOnlyRootFilesystem: true`, mount `/tmp` as `emptyDir`.
- **No privilege escalation**: `allowPrivilegeEscalation: false`.
- **Resource requests and limits**: Always set both CPU and memory.
- **Single process per container**: Do not run supervisord. Use sidecar pattern for auxiliary processes.
- **Logs to stdout/stderr**: No log files. Let the cluster log collector handle aggregation.
- **Configurable via env vars or mounted ConfigMaps/Secrets**: No hardcoded config.

---

### Step 8: Validate

- Run `docker build --check .` if Docker is available.
- Run `docker compose config` to validate compose syntax.
- Verify the Dockerfile has no obvious issues (missing WORKDIR, wrong COPY paths).
- Check that referenced files/dirs in COPY instructions exist.
- Verify HEALTHCHECK is present in production stages.
- Verify non-root USER is set in production stages.
- Check that no secrets are copied into image layers.
- Validate .dockerignore does not exclude files needed by COPY instructions.

### Step 9: Report

**Template:** `templates/report-template.txt`
Post-generation report template with files created summary, quick start commands, production deploy steps, and notes.

---

## Configuration

| Key | Type | Default | Description |
|---|---|---|---|
| `baseImage` | string | auto-detected | Override base image for final stage. |
| `registry` | string | `""` | Container registry prefix (e.g., `ghcr.io/org`). |
| `alwaysCompose` | boolean | `true` | Always generate `docker-compose.yml`. |
| `includeDevTarget` | boolean | `true` | Include development stage in Dockerfile. |
| `includeTestTarget` | boolean | `true` | Include test stage in Dockerfile. |
| `includeMonitoring` | boolean | `false` | Generate monitoring stack services. |
| `includeProxy` | boolean | `false` | Generate reverse proxy service. |
| `initProcess` | string | `"tini"` | Init process: `"tini"`, `"dumb-init"`, `"docker-init"`, or `"none"`. |
| `dockerignoreStrategy` | string | `"whitelist"` | `.dockerignore` strategy: `"whitelist"` or `"blacklist"`. |
| `platforms` | string[] | `["linux/amd64"]` | Target platforms for buildx. |
| `securityProfile` | string | `"hardened"` | `"hardened"` (Distroless, no-root, caps dropped) or `"standard"`. |
| `composeVersion` | string | `"3"` | Compose specification version. |
| `enableOtel` | boolean | `false` | Add OpenTelemetry collector to compose. |
| `dbEngine` | string | auto-detected | `"postgres"`, `"mysql"`, `"mongo"`, `"none"`. |
