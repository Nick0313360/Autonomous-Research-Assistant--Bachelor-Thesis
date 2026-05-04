---
name: genskills:env-setup
description: >
  Bootstrap local development environment - detect required tools, validate
  configuration, check services. Triggers on: "setup environment", "bootstrap",
  "why can't I run this", "dev setup", "environment check".
user-invocable: true
argument-hint: "[check|fix|full|security|onboard]"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(node *), Bash(npm *), Bash(npx *), Bash(python *), Bash(pip *), Bash(docker *), Bash(docker-compose *), Bash(git *), Bash(which *), Bash(where *), Bash(pnpm *), Bash(yarn *), Bash(nvm *), Bash(fnm *), Bash(volta *), Bash(pyenv *), Bash(conda *), Bash(rustup *), Bash(cargo *), Bash(java *), Bash(mise *), Bash(asdf *), Bash(brew *), Bash(apt *), Bash(dnf *), Bash(pacman *), Bash(wsl *), Bash(code *), Bash(curl *), Bash(openssl *), Bash(ssh *), Bash(ping *), Bash(nslookup *), Bash(dig *), Bash(netstat *), Bash(ss *), Bash(lsof *), Bash(uname *), Bash(cat *), Bash(ls *), Bash(env *), Bash(printenv *), Bash(systemctl *), Bash(pg_isready *), Bash(redis-cli *), Bash(mysql *), Bash(mongosh *), Bash(corepack *), Bash(sdkman *), Bash(dotnet *), Bash(go *), Bash(php *), Bash(composer *), Bash(ruby *), Bash(gem *), Bash(bundle *)"
genskills-version: "1.4.2"
genskills-category: "development"
genskills-depends: []
---

# Environment Setup

Bootstrap, validate, secure, and document a local development environment. This skill performs deep inspection of the project, the host machine, network conditions, and team conventions to get a developer from clone to running as fast as possible.

---

## Process

### Step 0: Load Project Context & Detect Platform

**Project context**:
- Read `CLAUDE.md` at the project root for setup instructions and tribal knowledge
- Read `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Read `.editorconfig`, `.prettierrc`, `.eslintrc.*`, `biome.json` for code style context

**Platform detection** - determine the host environment before anything else:

| Signal | How to detect | Why it matters |
|---|---|---|
| **OS family** | `uname -s` → `Linux`, `Darwin`, `MINGW64_NT-*` / `MSYS_NT-*` | Path separators, package managers, shell behavior |
| **Windows sub-environment** | Check `$MSYSTEM` (MINGW64 = Git Bash), `$WSL_DISTRO_NAME` (WSL2), `$PSModulePath` (PowerShell) | WSL2 has native Linux tooling; Git Bash has limited POSIX; PowerShell needs different syntax |
| **WSL2 specifics** | If WSL2: check `/mnt/c` mount performance, `wsl.conf` settings, whether Docker Desktop WSL integration is enabled (`docker context ls`) | Cross-filesystem I/O is 10-100x slower; projects should live inside the WSL filesystem |
| **macOS specifics** | Check for Xcode CLT (`xcode-select -p`), Homebrew (`brew --prefix`), Apple Silicon vs Intel (`uname -m` → `arm64` vs `x86_64`) | Many build tools need Xcode CLT; Homebrew paths differ on Apple Silicon (`/opt/homebrew` vs `/usr/local`) |
| **Linux distro** | `/etc/os-release` → detect Ubuntu/Debian (`apt`), Fedora/RHEL (`dnf`), Arch (`pacman`), Alpine (`apk`) | Package manager commands differ; some distros lack build essentials by default |
| **Container/cloud** | Check `/.dockerenv`, `$CODESPACES`, `$GITPOD_WORKSPACE_ID`, `$REMOTE_CONTAINERS` | Skip hardware-specific checks; adjust service discovery (localhost vs container names) |

**Platform-specific path warnings**:
- Windows: Flag `C:\` style paths in config files that should use forward slashes or `~`
- WSL2: Warn if project is on `/mnt/c/` (Windows filesystem) - recommend moving to `~/`
- macOS: Check if `/usr/local/bin` or `/opt/homebrew/bin` is in `$PATH`
- All: Verify line endings (`git config core.autocrlf`; check `.gitattributes`)

---

### Step 1: Detect Project Requirements

Read these files to understand what the project needs:

**Runtime & language**:
- `package.json` → `engines` field (Node.js version, npm/yarn/pnpm version), `packageManager` field (corepack), `type` (module vs commonjs)
- `.nvmrc` / `.node-version` → Node version for nvm/fnm
- `.tool-versions` → asdf runtime versions (any language)
- `.mise.toml` / `.mise.local.toml` → mise (formerly rtx) runtime versions
- `volta` key in `package.json` → Volta-pinned Node/npm/yarn
- `pyproject.toml` / `setup.cfg` / `requirements.txt` / `Pipfile` / `poetry.lock` → Python version, deps, build system
- `Cargo.toml` / `rust-toolchain.toml` → Rust version and edition
- `go.mod` → Go version
- `build.gradle` / `pom.xml` / `.sdkmanrc` → Java/Kotlin/Scala version
- `.ruby-version` / `Gemfile` → Ruby version
- `composer.json` → PHP version
- `global.json` → .NET SDK version

**Environment variables**:
- `.env.example` / `.env.sample` / `.env.template` / `.env.development` → required variables
- `docker-compose.yml` `environment:` and `env_file:` sections → service-level env vars
- `src/**/*.ts`, `src/**/*.py` → scan for `process.env.XXX` or `os.environ["XXX"]` patterns not covered by `.env.example`

**Infrastructure & services**:
- `docker-compose.yml` / `compose.yaml` / `compose.yml` → required services (postgres, redis, kafka, rabbitmq, minio, mailhog, etc.)
- `Dockerfile` / `Dockerfile.*` → base image, system dependencies, multi-stage build requirements
- `.devcontainer/devcontainer.json` → dev container configuration
- `.gitpod.yml` → Gitpod workspace setup
- `.github/codespaces/` or `devcontainer.json` → Codespaces configuration

**Build & CI**:
- `Makefile` / `Taskfile.yml` / `justfile` / `Rakefile` → build/setup commands
- `.github/workflows/*.yml` → CI environment for reference (what CI uses should work locally)
- `turbo.json` / `nx.json` / `lerna.json` → monorepo orchestration
- `tsconfig.json` / `tsconfig.*.json` → TypeScript configuration and path aliases
- `webpack.config.*` / `vite.config.*` / `next.config.*` / `nuxt.config.*` → bundler/framework config

**Documentation**:
- `README.md` / `CONTRIBUTING.md` / `docs/setup.md` → setup instructions
- `CHANGELOG.md` → recent breaking changes that may affect setup

---

### Step 2: Check Prerequisites & Runtimes

For each detected requirement, verify installation and version compatibility.

#### 2a: Version Manager Detection

Before checking runtime versions, detect which version manager is in use so you install/switch correctly:

| Runtime | Version managers (check in order) | How to detect |
|---|---|---|
| **Node.js** | Volta → fnm → nvm → mise → asdf → system | `volta --version`, `fnm --version`, `nvm --version` (or `$NVM_DIR`), `mise --version`, `asdf --version` |
| **Python** | pyenv → conda → mise → asdf → system | `pyenv --version`, `conda --version`, `mise --version` |
| **Rust** | rustup (almost always) | `rustup --version`, check `~/.rustup/` |
| **Java** | SDKMAN → mise → asdf → system | `sdk version` (or `$SDKMAN_DIR`), `mise --version` |
| **Ruby** | rbenv → rvm → mise → asdf → system | `rbenv --version`, `rvm --version` |
| **Go** | goenv → mise → asdf → system | `goenv --version` |
| **Multi-runtime** | mise → asdf | Both manage any runtime via plugins |

**Version manager actions**:
- If a `.nvmrc` exists and nvm is installed: suggest `nvm use` or `nvm install`
- If a `volta` key exists in `package.json`: verify Volta is installed, run `volta install`
- If `.tool-versions` exists and asdf is installed: suggest `asdf install`
- If `.mise.toml` exists: suggest `mise install`
- If no version manager is found but a version file exists: recommend installing the appropriate one for the platform

#### 2b: Runtime Versions

- `node --version` - compare against `engines`, `.nvmrc`, `.node-version`, or `volta` pin
- `python --version` / `python3 --version` - compare against `pyproject.toml` `requires-python`
- `rustc --version` - compare against `rust-toolchain.toml`
- `java --version` - compare against `build.gradle` `sourceCompatibility` or `.sdkmanrc`
- `go version` - compare against `go.mod` `go` directive
- `dotnet --version` - compare against `global.json`

For each: report installed version, required version, and whether they are compatible (not just exact match - respect semver ranges, `>=`, `^`, `~`).

#### 2c: Package Manager Verification

- Detect which package manager the project uses: look for lock files (`package-lock.json` → npm, `yarn.lock` → yarn, `pnpm-lock.yaml` → pnpm, `bun.lockb` → bun)
- If `packageManager` field exists in `package.json`, check if `corepack` is enabled: `corepack --version`
- Verify the package manager version matches what the project expects
- If using Yarn Berry (v2+): check `.yarnrc.yml` for `nodeLinker` setting (pnp vs node-modules)
- If using pnpm: check `.npmrc` for `shamefully-hoist`, `strict-peer-dependencies`

#### 2d: System-Level Dependencies

Check for tools that native modules or build steps often require:

| Dependency | Check command | Needed by |
|---|---|---|
| `gcc`/`g++`/`clang` | `gcc --version` or `cc --version` | node-gyp, native extensions |
| `make` | `make --version` | node-gyp, Makefiles |
| `python3` (for node-gyp) | `python3 --version` | node-gyp on Node 18+ |
| `pkg-config` | `pkg-config --version` | Native library linking |
| `cmake` | `cmake --version` | Some native modules |
| `openssl` headers | `openssl version` | Crypto-related packages |
| `libpq-dev` / `postgresql-devel` | Check via package manager | `pg` npm package, psycopg2 |
| `libvips` | `vips --version` | sharp (image processing) |

On macOS: check Xcode Command Line Tools - `xcode-select -p`; if missing, instruct `xcode-select --install`.
On Linux: check `build-essential` (Debian) or `Development Tools` group (Fedora).
On Windows: check for Visual Studio Build Tools or `windows-build-tools` npm package.

---

### Step 3: Environment Variables & Secrets

#### 3a: Completeness Check
- Parse `.env.example` (or equivalent) for all defined variable names
- Parse actual `.env` (if it exists) for all defined variable names
- Report: **missing** (in example but not in .env), **extra** (in .env but not in example), **placeholder** (values like `changeme`, `your-api-key-here`, `xxx`, `TODO`, `REPLACE_ME`, empty strings)
- Cross-reference with code: scan source files for `process.env.`, `os.environ`, `os.Getenv`, `env::var` to find env vars not documented in `.env.example`
- **Never display actual secret values** - only display variable names and whether they are set

#### 3b: Security Validation
- **Leaked secrets scan**: Check `.env` for values that look like real secrets accidentally committed - but only warn about patterns, never print values:
  - AWS keys: values matching `AKIA[0-9A-Z]{16}`
  - GitHub tokens: `ghp_`, `gho_`, `ghs_`, `ghr_` prefixes
  - Private keys: `-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----`
  - JWTs: `eyJ` prefix with two dots
  - Generic high-entropy strings in variables named `*_SECRET`, `*_KEY`, `*_TOKEN`, `*_PASSWORD`
- **Git history check**: Verify `.env` is in `.gitignore`; if not, **critical warning**
- **File permissions** (Linux/macOS): `.env` should be `600` or `640` - warn if world-readable
- Check for `.env` files in git history: `git log --all --diff-filter=A -- .env` (warn if previously committed)
- Validate that `pre-commit` or `husky` hooks include secret-scanning tools (e.g., `gitleaks`, `detect-secrets`, `trufflehog`)
- If no secret scanning hook exists, recommend adding one

#### 3c: SSL/TLS for Local HTTPS
If the project uses local HTTPS (e.g., `HTTPS=true`, `mkcert`, self-signed certs referenced in config):
- Check if certificate files exist at the referenced paths
- Validate certificate expiry: `openssl x509 -enddate -noout -in <cert>`
- Check if `mkcert` root CA is installed in the system trust store: `mkcert -CAROOT`
- Verify certificate matches the hostname used in local development

---

### Step 4: Dependencies

#### 4a: Installation Status
- Check if `node_modules/` exists and lock file is consistent
- Check if Python virtual environment exists (`.venv/`, `venv/`, or conda env)
- Check if `vendor/` exists (Go, PHP)
- Check if `target/` exists (Rust, Java)
- Verify lock file freshness: is lock file newer than the manifest file? If not, dependencies may be out of sync

#### 4b: Dependency Health
- **Vulnerabilities**: Run `npm audit --json` / `yarn audit --json` / `pnpm audit --json` and summarize critical/high findings
- **Outdated critical deps**: Run `npm outdated` and flag packages with major version bumps, especially frameworks (React, Next.js, Express, Django, etc.)
- **License compliance**: If a `license-checker` or similar tool is configured, run it; otherwise note that license checking is not configured
- **Native build deps**: If `package.json` includes packages known to need native compilation (`sharp`, `bcrypt`, `canvas`, `sqlite3`, `better-sqlite3`, `node-sass`), verify their system-level dependencies are present
- **Peer dependency conflicts**: Check for unmet peer dependencies (`npm ls` or equivalent)

#### 4c: Monorepo-Specific
If monorepo tooling is detected (`turbo.json`, `nx.json`, `lerna.json`, `pnpm-workspace.yaml`):
- Verify workspace configuration is correct
- Check if all workspace packages have their dependencies installed
- Verify hoisting configuration matches project expectations

---

### Step 5: Services & Infrastructure

#### 5a: Docker & Container Services
- Check if Docker daemon is running: `docker info`
- Check if Docker Compose is available: `docker compose version` (v2) or `docker-compose --version` (v1)
- If `docker-compose.yml` exists, check container status: `docker compose ps`
- Report: which services are running, which are stopped, which have never been started
- Check for port conflicts: are any required ports already in use? (`lsof -i :PORT` or `netstat -tlnp`)

#### 5b: Database Connectivity & State
For each detected database:

| Database | Detection | Connectivity check | Migration check |
|---|---|---|---|
| **PostgreSQL** | `DATABASE_URL` containing `postgres`, docker service `postgres`/`db` | `pg_isready -h HOST -p PORT` | Check for `prisma`, `knex`, `typeorm`, `sequelize`, `alembic`, `django` migration tools; report pending migrations |
| **MySQL/MariaDB** | `DATABASE_URL` containing `mysql`, docker service `mysql`/`mariadb` | `mysqladmin ping -h HOST` | Same migration tool detection |
| **MongoDB** | `MONGODB_URI`, docker service `mongo` | `mongosh --eval "db.runCommand({ping:1})"` | Check for mongoose migration scripts |
| **Redis** | `REDIS_URL`, docker service `redis` | `redis-cli -h HOST ping` | N/A |
| **SQLite** | `DATABASE_URL` containing `sqlite`, `.db` files | Check file exists and is readable | Same migration tool detection |

**Migration status** (when migration tool detected):
- Prisma: `npx prisma migrate status`
- Knex: `npx knex migrate:status`
- Django: `python manage.py showmigrations`
- Alembic: `alembic current` vs `alembic heads`
- Rails: `rails db:migrate:status`

#### 5c: Message Queues & Event Streaming
| Service | Detection | Check |
|---|---|---|
| **RabbitMQ** | `AMQP_URL`, `RABBITMQ_URL`, docker service `rabbitmq` | `curl -s http://HOST:15672/api/healthchecks/node` (management API) |
| **Kafka** | `KAFKA_BROKERS`, docker service `kafka`/`redpanda` | Check if broker port is open and accepting connections |
| **Redis Pub/Sub** | `REDIS_URL` with pub/sub usage in code | Same as Redis connectivity above |
| **NATS** | `NATS_URL`, docker service `nats` | `curl -s http://HOST:8222/healthz` |

#### 5d: Object Storage
| Service | Detection | Check |
|---|---|---|
| **S3/MinIO** | `AWS_S3_BUCKET`, `S3_ENDPOINT`, `MINIO_ENDPOINT`, docker service `minio` | Check endpoint reachability; verify bucket exists if credentials are set |
| **Local filesystem** | `UPLOAD_DIR`, `STORAGE_PATH` | Check directory exists and is writable |

#### 5e: Email / SMTP
| Service | Detection | Check |
|---|---|---|
| **Mailhog/Mailpit** | docker service `mailhog`/`mailpit`, `SMTP_HOST=localhost` | Check web UI port (8025) is reachable |
| **External SMTP** | `SMTP_HOST`, `MAIL_HOST`, `EMAIL_SERVER` | Verify host is resolvable (do not attempt auth) |

#### 5f: External API & OAuth Providers
- Scan `.env.example` for variables matching `*_API_KEY`, `*_CLIENT_ID`, `*_CLIENT_SECRET`, `*_OAUTH_*`
- For each: check if the corresponding `.env` value is set (not empty, not placeholder)
- If a known provider is detected (e.g., `GITHUB_CLIENT_ID`, `GOOGLE_CLIENT_ID`, `STRIPE_SECRET_KEY`, `TWILIO_*`), note the provider name for the report
- Do NOT attempt to validate keys against remote APIs (security risk) - only check they are present and non-placeholder

---

### Step 6: Network Diagnostics

Especially important in corporate environments, VPN-connected machines, and containerized setups.

#### 6a: Proxy Configuration
- Check for proxy env vars: `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `http_proxy`, `https_proxy`
- Check npm proxy settings: `npm config get proxy`, `npm config get https-proxy`
- Check git proxy settings: `git config --global http.proxy`
- If a proxy is set: verify it is reachable
- If no proxy is set but connectivity fails: suggest checking corporate proxy requirements

#### 6b: DNS Resolution
- Resolve key hostnames used in the project (database hosts, API endpoints in `.env`)
- If resolution fails: check `/etc/resolv.conf` (Linux) or `scutil --dns` (macOS) for DNS configuration
- Check for common DNS issues: VPN split-tunnel misconfiguration, stale `/etc/hosts` entries

#### 6c: Port Availability
- For each service in `docker-compose.yml`, check if the host-mapped port is available
- For the dev server port (from `package.json` scripts, framework config), check availability
- Report which process holds the port if it is occupied: `lsof -i :PORT` or `netstat -tlnp | grep PORT`

#### 6d: SSL Certificate Chain
If the project connects to external services over HTTPS:
- `openssl s_client -connect HOST:443 -servername HOST` to verify certificate chain
- Useful when corporate proxies do MITM SSL inspection - the CA cert may need to be added to Node's `NODE_EXTRA_CA_CERTS`

---

### Step 7: IDE & Editor Setup

#### 7a: VS Code
If `.vscode/` directory or workspace file exists:
- Check for recommended extensions in `.vscode/extensions.json` - verify they are listed
- If no `extensions.json` exists, suggest creating one based on detected project stack:
  - TypeScript → `dbaeumer.vscode-eslint`, `esbenp.prettier-vscode`
  - Python → `ms-python.python`, `ms-python.vscode-pylance`
  - Rust → `rust-lang.rust-analyzer`
  - Go → `golang.go`
  - Docker → `ms-azuretools.vscode-docker`
  - Tailwind → `bradlc.vscode-tailwindcss`
  - Prisma → `Prisma.prisma`
- Check `.vscode/settings.json` for formatOnSave, default formatter, path aliases
- Check `.vscode/launch.json` for debugging configurations - if missing and a debuggable framework is detected, suggest generating one:
  - Next.js: server-side + client-side debug configs
  - Express/Fastify: Node.js attach config
  - Python/Django: Python debugger config
  - Rust: CodeLLDB config

#### 7b: JetBrains IDEs
If `.idea/` directory or `*.iml` files exist:
- Check for run configurations in `.idea/runConfigurations/`
- Verify `.idea/` gitignore patterns are appropriate (some files should be shared, some should not)

#### 7c: Dev Container
If `.devcontainer/devcontainer.json` exists:
- Validate JSON syntax
- Check that referenced Dockerfile exists
- Verify `forwardPorts` matches services in `docker-compose.yml`
- Check `postCreateCommand` and `postStartCommand` for setup steps
- If VS Code is detected: suggest "Reopen in Container" workflow

If no dev container config exists but Docker is heavily used: suggest creating one to standardize the environment.

#### 7d: GitHub Codespaces & Gitpod
- If `.devcontainer/` exists: note that Codespaces is supported
- If `.gitpod.yml` exists: validate task definitions, port configurations
- Detect if current environment IS a Codespace or Gitpod workspace and adjust service checks accordingly (use container hostnames, skip Docker-in-Docker checks)

---

### Step 8: Performance Baseline

Measure initial build/test/startup times so future regressions can be detected. Only run when `$ARGUMENTS` is `full` or explicitly requested.

| Metric | How to measure | What to record |
|---|---|---|
| **Cold install** | Time `npm ci` / `pip install` / `cargo build` | Duration in seconds |
| **Build** | Time the project's build command (`npm run build`, `cargo build --release`, etc.) | Duration, output size |
| **Test suite** | Time `npm test` / `pytest` / `cargo test` | Duration, pass/fail count |
| **Dev server startup** | Time from command invocation to "ready" message | Duration to first request |
| **TypeScript type check** | `tsc --noEmit` timing | Duration |

Store results in `${CLAUDE_SKILL_DIR}/_perf-baseline.json`:

**Template:** `templates/performance-baseline.json` - Example structure for storing performance baseline metrics (timestamps, platform info, and timing measurements).

On subsequent runs, compare against baseline and flag significant regressions (>20% slower).

---

### Step 9: Report or Fix

**If `$ARGUMENTS` is `check`** (default):
- Report everything that is missing or misconfigured
- Provide specific, copy-paste-ready fix instructions
- Prioritize issues: critical (blocks running) → warning (may cause problems) → info (nice-to-have)

**If `$ARGUMENTS` is `fix`**:
- Install missing dependencies (`npm install`, `pip install -r requirements.txt`, etc.)
- Copy `.env.example` to `.env` if missing (warn user to fill in secrets)
- Start required Docker services: `docker compose up -d`
- Run pending database migrations (with confirmation)
- Set appropriate file permissions on `.env` (Linux/macOS)
- Run build to verify

**If `$ARGUMENTS` is `full`**:
- Run both check and fix
- Run performance baseline measurements
- Run build to verify everything works
- Run test suite to confirm setup
- Run dev server briefly to verify it starts
- Generate onboarding artifacts (see Step 10)

**If `$ARGUMENTS` is `security`**:
- Run only the security-related checks (Step 3b, 3c)
- Deep scan for secrets in git history
- Validate file permissions across all config files
- Check for secret-scanning git hooks
- Report security posture summary

**If `$ARGUMENTS` is `onboard`**:
- Run full check
- Generate onboarding artifacts (see Step 10)
- Do not auto-fix - document everything for the new developer

---

### Step 10: Team Onboarding & Setup Automation

When `$ARGUMENTS` is `full` or `onboard`, generate artifacts to help future developers.

#### 10a: Onboarding Checklist
Generate a `SETUP_CHECKLIST.md` (only if it does not already exist) containing:
- Accounts needed (based on OAuth providers and external APIs detected)
- Tools to install (with exact version and install command for the detected platform)
- Steps in order (clone, install version manager, install runtime, install deps, configure env, start services, run migrations, verify build, run tests)
- Common first-day gotchas discovered during this setup
- Links to relevant internal docs if referenced in README or CONTRIBUTING

#### 10b: Setup Script
Generate a `setup.sh` (only if it does not already exist) that automates the fixable steps:

**Template:** `templates/setup-script.sh` - Starter setup script with prerequisite checks, dependency installation, env configuration, service startup, and build verification.

#### 10c: Tribal Knowledge Capture
During setup, document any non-obvious discoveries:
- Undocumented environment variables found in source but not in `.env.example`
- Services referenced in code but not in `docker-compose.yml`
- Version constraints that are not documented (e.g., "Node 21 breaks X")
- Platform-specific workarounds needed
- Store in a structured comment block at the end of the generated `SETUP_CHECKLIST.md`

---

### Step 11: Final Report

Always end with a structured report. Adapt verbosity to the number of issues found.

**Template:** `templates/final-report.md` - Example final report structure with sections for platform, passing checks, warnings, critical issues, fix commands, performance baseline, and quick start.

---

## Configuration

Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:

**Template:** `templates/config-defaults.json` - Default configuration values for all skill options.

| Key | Type | Default | Description |
|---|---|---|---|
| `autoFix` | boolean | `false` | Automatically fix issues without asking |
| `checkServices` | boolean | `true` | Check Docker services and database connectivity |
| `checkBuild` | boolean | `false` | Verify build works (always `true` for `full`) |
| `checkSecurity` | boolean | `true` | Run secret scanning and permission checks |
| `checkNetwork` | boolean | `true` | Run network diagnostics (DNS, proxy, ports) |
| `checkPerformance` | boolean | `false` | Measure build/test/startup times (always `true` for `full`) |
| `generateOnboarding` | boolean | `false` | Generate onboarding artifacts (always `true` for `full`/`onboard`) |
| `skipPorts` | number[] | `[]` | Ports to skip when checking availability |
| `customChecks` | string[] | `[]` | Additional shell commands to run as health checks |
| `proxy` | string | `null` | Override proxy URL for all network checks |
| `trustedCACert` | string | `null` | Path to CA certificate for corporate SSL inspection |
