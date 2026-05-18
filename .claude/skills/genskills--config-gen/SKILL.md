---
name: genskills:config-gen
description: >
  Generate and sync config files - ESLint, Prettier, TSConfig, Tailwind, Vite, Webpack.
  Triggers on: "generate config", "add eslint", "add prettier", "setup linting",
  "tsconfig", "configure tooling".
user-invocable: true
argument-hint: "[tool] - e.g., 'eslint' or 'prettier' or 'all'"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(npm *), Bash(npx *), Bash(pnpm *), Bash(yarn *)"
genskills-version: "1.4.2"
genskills-category: "development"
genskills-depends: []
---

# Config Gen

Generate best-practice, production-grade configuration files for development tooling. Handles single-tool setup, full-stack config orchestration, monorepo configuration, conflict resolution between overlapping tools, and config-as-code packaging for organizations.

---

## Process

### Step 0: Load Context

- Check `CLAUDE.md` for project conventions (formatting rules, naming, preferred tools).
- Check `${CLAUDE_SKILL_DIR}/_config.json` for saved preferences from prior runs.
- Read the root `package.json` to determine existing dependencies, scripts, and workspaces.
- Detect lockfile (`package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lockb`) to identify package manager.
- Scan for existing config files to understand what is already configured and avoid destructive overwrites.

### Step 1: Parse Arguments

Parse `$ARGUMENTS`:
- `$0` = tool name, comma-separated list of tools, or `"all"`
- `--style` = config style: `"strict"` | `"recommended"` | `"minimal"`
- `--env` = target environment override: `"development"` | `"production"` | `"ci"`
- `--monorepo` = force monorepo mode even if workspaces are not auto-detected
- `--dry-run` = show what would be generated without writing files

Supported tools:

| Category | Tools |
|---|---|
| **Linting** | `eslint`, `biome`, `oxlint`, `stylelint`, `commitlint` |
| **Formatting** | `prettier`, `biome` (formatter mode), `editorconfig` |
| **TypeScript** | `tsconfig`, `tsconfig-paths`, `declaration-files` |
| **Bundlers** | `vite`, `webpack`, `turbopack`, `rspack` |
| **Compilers/Transforms** | `swc`, `babel`, `postcss` |
| **CSS/Styling** | `tailwind`, `postcss`, `stylelint` |
| **Testing** | `vitest`, `jest` |
| **Git Hooks** | `husky`, `lint-staged`, `lefthook`, `commitlint` |
| **Release/Versioning** | `semantic-release`, `changesets`, `syncpack` |
| **Dependency Management** | `renovate`, `dependabot`, `knip` |
| **CI/CD** | `github-actions`, `docker`, `nginx`, `pm2` |
| **Security** | `csp`, `cors`, `helmet`, `security-headers` |

If `"all"` or no args: detect stack and generate all relevant configs.

### Step 2: Detect Project Stack

Perform deep project analysis:

- **Language**: TypeScript vs JavaScript. If TS, check `strict` mode status, composite project settings, path aliases.
- **Framework**: React, Next.js, Remix, Vue, Nuxt, Svelte, SvelteKit, Astro, Solid, Node.js, Express, Fastify, Hono, NestJS, etc.
- **Runtime**: Node.js (version from `.nvmrc`, `engines`, or `volta`), Deno, Bun.
- **Monorepo**: Detect workspaces in `package.json`, `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, `lerna.json`. Map the workspace graph.
- **Existing configs**: Catalog every config file present. Never overwrite without asking - merge intelligently or prompt the user.
- **Package manager**: npm, pnpm, yarn (classic or berry), bun. Respect the lockfile.
- **Config conflicts**: Identify mutually exclusive tools early (see Step 2b).

#### Step 2b: Config Conflict Resolution

Before generating anything, detect and resolve conflicts:

**Mutually exclusive tool pairs:**
- ESLint + Prettier vs Biome (Biome replaces both). If both are requested, warn and ask which approach to use.
- Prettier vs Biome formatter. They cannot coexist on the same file types without race conditions.
- oxlint vs ESLint. oxlint can supplement ESLint for speed but overlapping rules must be disabled in one.

**Overlapping rule detection:**
- When ESLint has both `@typescript-eslint` and framework plugins (e.g., `eslint-plugin-react`), check for conflicting rule definitions (e.g., `no-unused-vars` vs `@typescript-eslint/no-unused-vars`).
- When Prettier and ESLint both touch formatting, ensure `eslint-config-prettier` is installed and listed last in extends to disable conflicting rules.
- When Stylelint and Prettier both format CSS, ensure `stylelint-config-prettier` disables formatting rules in Stylelint.

**TypeScript strict mode conflicts:**
- Next.js requires certain `compilerOptions` that may conflict with maximum strictness (e.g., `moduleResolution: "bundler"`, `jsx: "preserve"`).
- Some frameworks inject their own `tsconfig` base via `extends` - detect this and layer additional strict options on top without breaking the framework contract.
- When `strict: true` is enabled incrementally, track which strict flags are active and which are deferred.

**Resolution strategy:**
1. Detect all conflicts before generating any files.
2. Present conflicts to the user with a recommended resolution.
3. Apply the chosen resolution, adding comments in generated configs explaining why certain rules are disabled or overridden.

### Step 3: Generate Configs

---

#### 3.1 - ESLint (`eslint.config.js` / `eslint.config.mjs` - flat config)

- Use ESLint v9+ flat config format exclusively. Never generate `.eslintrc.*` legacy configs.
- Include framework-specific plugins: `eslint-plugin-react`, `eslint-plugin-react-hooks`, `eslint-plugin-vue`, `eslint-plugin-svelte`, `eslint-plugin-astro`, etc.
- TypeScript parser (`typescript-eslint`) if TS project, with `parserOptions.project` pointing to the correct tsconfig.
- Import ordering via `eslint-plugin-import-x` (the maintained fork) with path group configuration.
- Accessibility rules: `eslint-plugin-jsx-a11y` for React, `eslint-plugin-vuejs-accessibility` for Vue.
- **Performance configuration:**
  - Enable `eslint --cache` in the lint script with `.eslintcache` in `.gitignore`.
  - Use `TIMING=1` environment variable support for rule timing benchmarks.
  - For large projects, configure `eslint.config.js` to scope type-aware rules only to source files (not config files) to reduce overhead.
- **Environment-specific overrides:**
  - Test files (`**/*.test.ts`, `**/*.spec.ts`, `**/__tests__/**`): relax rules - allow `any`, allow magic numbers, disable `no-console`.
  - Config/script files (`*.config.ts`, `scripts/**`): allow `require`, `process.env`, default exports.
  - CI mode: configure scripts for `--max-warnings 0` to fail on any warning.

---

#### 3.2 - Biome (`biome.json` / `biome.jsonc`)

Deep configuration as an ESLint + Prettier replacement:

**Template:** `templates/biome-config.jsonc`
Full Biome configuration with VCS integration, formatter, linter rules, and test file overrides.

- Configure VCS integration so Biome respects `.gitignore`.
- Set up overrides for test files, config files, and generated code.
- If migrating from ESLint + Prettier, run `biome migrate eslint` and `biome migrate prettier` to port existing rules.

---

#### 3.3 - oxlint (`oxlint.json` / `.oxlintrc.json`)

- Configure as a fast supplementary linter alongside ESLint, or as a standalone replacement for simpler projects.
- Disable rules that overlap with ESLint to avoid double-reporting.
- Focus oxlint on performance-sensitive rules it handles well: `no-unused-vars`, import validation, correctness checks.
- Add `oxlint` as a pre-ESLint step in CI for fast-fail on obvious issues.

---

#### 3.4 - Prettier (`.prettierrc`)

**Template:** `templates/prettier-config.json`
Default Prettier configuration with semicolons, single quotes, and LF line endings.

- Add `.prettierignore` covering `dist/`, `build/`, `coverage/`, lockfiles, generated files, and `*.min.*`.
- Add framework plugins:
  - `prettier-plugin-tailwindcss` - must be listed last in plugins array.
  - `prettier-plugin-svelte`, `prettier-plugin-astro`, `@prettier/plugin-xml` as needed.
  - `prettier-plugin-organize-imports` or `prettier-plugin-sort-imports` if import sorting is handled by Prettier rather than ESLint.
- Ensure `eslint-config-prettier` is installed and integrated into ESLint config when both tools coexist.

---

#### 3.5 - TypeScript (`tsconfig.json` and variants)

Generate a multi-file TypeScript configuration:

**`tsconfig.base.json`** (shared compiler options):
**Template:** `templates/tsconfig-base.json`
Shared base TypeScript compiler options with strict mode, ES2022 target, and bundler module resolution.

**`tsconfig.json`** (main project config):
- Extends `tsconfig.base.json`.
- Includes source directories, excludes `node_modules`, `dist`, test files.
- Path aliases synced with the bundler (`@/*` pointing to `src/*`).

**`tsconfig.build.json`** (production build):
- Extends `tsconfig.json`.
- Excludes test files, stories, mocks.
- Enables `incremental: true` with `tsBuildInfoFile` for faster rebuilds.
- Sets `noEmit: true` or configures `outDir` depending on whether a bundler handles emit.

**`tsconfig.test.json`** (test environment):
- Extends `tsconfig.json`.
- Includes test directories and setup files.
- Relaxes strictness where tests benefit: `"noPropertyAccessFromIndexSignature": false`.
- Sets appropriate `types` for the test framework (`vitest/globals`, `jest`, `@testing-library/jest-dom`).

**`tsconfig.scripts.json`** (build scripts, tooling):
- Targets Node.js specifically with `"module": "NodeNext"`, `"moduleResolution": "NodeNext"`.
- Includes only `scripts/` directory.

**Path alias synchronization:**
- When `tsconfig.json` defines `paths`, sync them into:
  - `vite.config.ts` via `resolve.alias`
  - `jest.config.ts` via `moduleNameMapper`
  - `vitest.config.ts` via `resolve.alias`
  - Webpack via `resolve.alias`
  - `eslint-import-resolver-typescript` for ESLint import resolution

**Monorepo composite projects:**
- Enable `composite: true` and `references` in the root tsconfig.
- Each package gets its own `tsconfig.json` extending the shared base.
- Configure `tsc --build` mode for incremental cross-package compilation.

**Strict mode migration (incremental):**
- For projects not yet on `strict: true`, generate a tsconfig that enables strict flags one at a time:
  - Phase 1: `noImplicitAny`, `strictNullChecks`
  - Phase 2: `strictFunctionTypes`, `strictBindCallApply`
  - Phase 3: `strictPropertyInitialization`, `noImplicitReturns`
  - Phase 4: `strict: true` (replaces all individual flags)
- Add comments documenting which phase the project is in and what remains.

**Custom type augmentation files:**
- Generate `src/types/env.d.ts` for environment variable types (`ImportMetaEnv` for Vite, `ProcessEnv` for Node).
- Generate `src/types/global.d.ts` for global type extensions.
- Generate `src/types/modules.d.ts` for untyped module declarations (`.svg`, `.css`, `.png`, etc.).

---

#### 3.6 - Tailwind (`tailwind.config.ts`)

- Content paths matching project structure (detect `src/`, `app/`, `pages/`, `components/` directories).
- Theme extensions: spacing scale, color palette (generate from brand colors if provided), font families, breakpoints.
- Plugin configuration: `@tailwindcss/typography`, `@tailwindcss/forms`, `@tailwindcss/container-queries`, `tailwindcss-animate`.
- For Tailwind v4+, generate the CSS-based configuration format instead of `tailwind.config.ts`.
- Dark mode strategy: `class` (for manual toggle) or `media` (for OS preference).

---

#### 3.7 - Vite (`vite.config.ts`)

- Framework plugin: `@vitejs/plugin-react`, `@vitejs/plugin-react-swc`, `@vitejs/plugin-vue`, `@sveltejs/vite-plugin-svelte`.
- Path aliases matching tsconfig `paths`.
- **Build optimization (production):**
  - `build.rollupOptions.output.manualChunks` for vendor splitting (split `react`, `react-dom`; split large libs individually).
  - `build.chunkSizeWarningLimit` set appropriately.
  - `build.cssCodeSplit: true` for route-based CSS splitting.
  - `build.minify: 'esbuild'` (default) or `'terser'` for maximum compression.
  - `build.sourcemap: true` for production debugging (or `'hidden'` to avoid exposing to browsers).
- **Dev server:**
  - Proxy configuration for API calls.
  - HMR configuration for containerized environments.
- **CSS handling:**
  - PostCSS integration via `css.postcss`.
  - CSS modules configuration if used.
  - Preprocessor options (Sass, Less).
- **Image optimization:**
  - `vite-plugin-image-optimizer` or `vite-plugin-imagemin` configuration for automatic image compression.
- **Font optimization:**
  - `vite-plugin-webfont-dl` for self-hosting Google Fonts.

---

#### 3.8 - Webpack (`webpack.config.js` / `webpack.config.ts`)

- Mode-specific configurations with `webpack-merge` for dev/prod splitting.
- **Optimization:**
  - `splitChunks` configuration: separate vendor chunk, framework chunk, common async chunks.
  - `TerserPlugin` with `parallel: true` for production minification.
  - `CssMinimizerPlugin` for CSS.
  - `ModuleFederationPlugin` setup for micro-frontends if applicable.
- **Loaders:**
  - `ts-loader` or `babel-loader` (or `swc-loader` for speed).
  - `css-loader`, `postcss-loader`, `sass-loader` chain.
  - Asset modules for images, fonts, SVGs.
- **Caching:**
  - `cache: { type: 'filesystem' }` for persistent build cache.
  - Content hashes in output filenames for long-term caching.
- **Bundle analysis:**
  - `webpack-bundle-analyzer` as an optional plugin for investigating bundle size.

---

#### 3.9 - Turbopack / Rspack

**Turbopack** (for Next.js):
- Enable via `next.config.js` experimental flag.
- Document known limitations vs Webpack compatibility.
- Configure custom loaders where supported.

**Rspack** (`rspack.config.js`):
- Near drop-in replacement for Webpack with SWC-based transforms.
- Builtin plugins for CSS extraction, HTML generation, copy.
- `builtins.html`, `builtins.copy`, `builtins.define` for zero-plugin simple configs.
- SWC loader configuration for TypeScript and JSX.

---

#### 3.10 - SWC (`.swcrc`)

**Template:** `templates/swc-config.json`
SWC configuration with TypeScript + TSX parsing, React automatic runtime, and decorator support.

- Configure decorator support for NestJS or similar frameworks.
- Set appropriate compilation target matching tsconfig.
- Enable emotion/styled-components plugin if CSS-in-JS is detected.

---

#### 3.11 - Babel (`babel.config.js` / `.babelrc.json`)

- Only generate if project specifically requires Babel (legacy projects, certain plugins with no SWC equivalent).
- Presets: `@babel/preset-env` (with browserslist), `@babel/preset-typescript`, `@babel/preset-react`.
- Plugins: `@babel/plugin-transform-runtime` for helper deduplication.
- Configure `browserslist` in `package.json` to drive both Babel and PostCSS/Autoprefixer targets.

---

#### 3.12 - PostCSS (`postcss.config.js`)

**Template:** `templates/postcss-config.js`
PostCSS configuration with Tailwind CSS, nesting, autoprefixer, and production-only cssnano.

- Include `postcss-import` for CSS `@import` inlining.
- Include `autoprefixer` driven by `browserslist`.
- Include `cssnano` in production only for minification.
- Include `tailwindcss/nesting` if Tailwind CSS is used with nested CSS syntax.
- Include `postcss-custom-media` or `postcss-preset-env` for modern CSS features targeting older browsers.

---

#### 3.13 - Stylelint (`.stylelintrc.json`)

- Base config: `stylelint-config-standard` or `stylelint-config-standard-scss` for Sass projects.
- Tailwind support: `stylelint-config-tailwindcss` to recognize `@tailwind`, `@apply`, `@layer` directives.
- Order plugin: `stylelint-config-rational-order` or `stylelint-order` for property ordering.
- Disable formatting rules when Prettier is used: `stylelint-config-prettier`.
- Custom rules for BEM naming convention if applicable.
- Add `.stylelintignore` for build output and generated files.

---

#### 3.14 - commitlint (`commitlint.config.js`)

**Template:** `templates/commitlint-config.js`
Commitlint configuration extending conventional commits with scope enum and header length rules.

- Auto-populate `scope-enum` from monorepo package names or meaningful project directories.
- Support custom commit types beyond conventional commits if the project uses them.
- Integrate with `semantic-release` or `changesets` for automated versioning.

---

#### 3.15 - Git Hooks Pipeline

**Husky v9** (`.husky/`):

```bash
# .husky/pre-commit
lint-staged

# .husky/commit-msg
npx --no -- commitlint --edit $1

# .husky/pre-push
npm run typecheck && npm run test:ci
```

- Initialize with `npx husky init`.
- Configure `prepare` script in `package.json`: `"prepare": "husky"`.
- Make hook files executable.

**lint-staged** (`lint-staged.config.js`):

**Template:** `templates/lint-staged-config.js`
lint-staged configuration with per-filetype linting, formatting, and typecheck commands.

- Use function syntax for commands that should run on the entire project (like `tsc`) rather than per-file.
- Order commands so linters run before formatters.

**Lefthook** (`lefthook.yml`) - as an alternative to Husky + lint-staged:

**Template:** `templates/lefthook-config.yml`
Lefthook configuration with parallel pre-commit hooks (lint, format, typecheck), commit-msg, and pre-push.

- Lefthook supports parallel execution natively, making it faster than Husky + lint-staged.
- No need for a separate `lint-staged` config - everything is in one file.

**Branch naming validation** (in `pre-push` or as a custom hook):
- Enforce patterns like `feature/*`, `fix/*`, `chore/*`, `release/*`.
- Block direct pushes to `main`/`master`/`develop`.

---

#### 3.16 - semantic-release (`.releaserc.json`)

**Template:** `templates/semantic-release-config.json`
semantic-release configuration with commit analyzer, changelog, npm publish, and GitHub release plugins.

- Configure branch strategy: `main` for production, `next`/`beta`/`alpha` for pre-releases.
- Set `npmPublish: false` for applications (non-library projects).
- Integrate with GitHub releases for automated changelogs.

---

#### 3.17 - Changesets (`.changeset/config.json`)

**Template:** `templates/changesets-config.json`
Changesets configuration with GitHub changelog integration and patch-level internal dependency updates.

- For monorepos, configure `linked` groups (packages that should version together) and `fixed` groups (packages that must share a version).
- Add versioning scripts to `package.json`: `"changeset": "changeset"`, `"version-packages": "changeset version"`, `"release": "changeset publish"`.
- Generate GitHub Actions workflow for automated Changesets PR creation.

---

#### 3.18 - Renovate / Dependabot

**Renovate** (`renovate.json`):
**Template:** `templates/renovate-config.json`
Renovate configuration with automerge for minor/dev dependencies, weekly schedule, and vulnerability alerts.

**Dependabot** (`.github/dependabot.yml`):
**Template:** `templates/dependabot-config.yml`
Dependabot configuration for npm and GitHub Actions with grouped tooling and testing updates.

---

#### 3.19 - Knip (unused exports/dependencies) (`knip.json`)

**Template:** `templates/knip-config.json`
Knip configuration for detecting unused files, exports, dependencies, and types.

- Detect and report unused files, exports, dependencies, and types.
- Add `"knip": "knip"` script to `package.json`.
- Configure `entry` and `project` paths matching the project structure.
- For monorepos, configure per-workspace entry points via the `workspaces` key.

---

#### 3.20 - Syncpack (monorepo version consistency) (`.syncpackrc`)

**Template:** `templates/syncpack-config.json`
Syncpack configuration enforcing workspace protocol for internal packages and consistent TypeScript versions.

- Enforce consistent versions of shared dependencies across all workspace packages.
- Use `workspace:*` protocol for internal package references.
- Add `"syncpack:check": "syncpack lint"` and `"syncpack:fix": "syncpack fix-mismatches"` scripts.

---

#### 3.21 - GitHub Actions (Reusable Workflows)

**CI workflow** (`.github/workflows/ci.yml`):
**Template:** `templates/github-actions-ci.yml`
GitHub Actions CI workflow with parallel lint, typecheck, test jobs and a dependent build job.

- Detect package manager and adjust setup steps accordingly.
- Use `concurrency` to cancel redundant runs on the same PR.
- Split jobs for parallelism: lint, typecheck, test, build.
- For monorepos, add path-based filtering so only affected packages are tested.

**Reusable workflow** (`.github/workflows/reusable-node-ci.yml`):
- Parameterize Node version, package manager, scripts to run.
- Callable from other repos: `uses: org/shared-workflows/.github/workflows/reusable-node-ci.yml@main`.

---

#### 3.22 - Docker (`Dockerfile` + `docker-compose.yml`)

**Multi-stage Dockerfile:**
**Template:** `templates/dockerfile-multistage`
Multi-stage Dockerfile with base, deps, build, and production stages using Node 20 Alpine.

- Multi-stage build to minimize production image size.
- Use `.dockerignore` to exclude `node_modules`, `.git`, tests, docs.
- Non-root user in production stage.
- Detect the project type (Next.js, Node API, static site) and adjust the Dockerfile accordingly.

**`docker-compose.yml`** for local development:
**Template:** `templates/docker-compose-dev.yml`
Docker Compose for local development with app service (volume mounts, hot reload) and PostgreSQL database.

---

#### 3.23 - Nginx (`nginx.conf`)

Generate Nginx configuration for SPA hosting or reverse proxy:

- SPA config: `try_files $uri $uri/ /index.html` for client-side routing.
- Security headers: HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy.
- Gzip/Brotli compression for text assets.
- Cache-Control headers: immutable for hashed assets, no-cache for `index.html`.
- Rate limiting on API proxy routes.
- SSL configuration if applicable (strong cipher suite, OCSP stapling).

---

#### 3.24 - PM2 (`ecosystem.config.js`)

**Template:** `templates/pm2-ecosystem-config.js`
PM2 ecosystem configuration with cluster mode, memory limits, environment variables, and log settings.

- Cluster mode with `instances: 'max'` for CPU utilization.
- Memory limit with `max_memory_restart`.
- Log configuration with rotation.
- Environment-specific variable sets.

---

#### 3.25 - Security Configs

**CSP (Content Security Policy):**
- Generate a `csp.config.js` or inline header configuration.
- Start with a strict policy (`default-src 'self'`) and widen based on detected dependencies (CDN scripts, analytics, fonts, images).
- Support for nonce-based script loading for inline scripts.
- Report-URI / report-to configuration for monitoring violations.

**Helmet configuration** (Express/Fastify):
**Template:** `templates/helmet-security-config.js`
Helmet security configuration with CSP directives, HSTS, CORS policies, and security headers.

**CORS configuration:**
- Generate `cors.config.js` with allowed origins (from environment variables), methods, headers, credentials support.
- Warn about `origin: '*'` with `credentials: true` (disallowed by browsers).

**Cookie security settings:**
- `httpOnly: true`, `secure: true`, `sameSite: 'strict'` or `'lax'` defaults.
- Appropriate `maxAge` / `expires` settings.
- Cookie prefix (`__Host-` / `__Secure-`) recommendations.

**Subresource Integrity (SRI):**
- Configure build pipeline to generate `integrity` attributes for CDN-hosted scripts and stylesheets.
- Webpack: `webpack-subresource-integrity` plugin.
- Vite: `vite-plugin-sri` or manual implementation.

---

#### 3.26 - EditorConfig (`.editorconfig`)

**Template:** `templates/editorconfig.ini`
EditorConfig with per-filetype indent settings for JS/TS, Go, Rust, YAML, Markdown, and Dockerfiles.

---

### Step 4: Monorepo Configuration

When a monorepo is detected (or `--monorepo` flag is set), apply these additional patterns:

#### Root-level configs
- Root `eslint.config.js` with shared base rules; packages extend or override.
- Root `tsconfig.base.json` with shared compiler options; per-package `tsconfig.json` extends it.
- Root `prettier` config (shared across all packages).
- Root `biome.json` covering the entire workspace.
- `turbo.json` or `nx.json` for task orchestration.

#### Shared config packages
When the monorepo is large enough to warrant it, generate shared config packages:

- `packages/eslint-config-custom/` - publishable ESLint config extending recommended rules with org overrides.
- `packages/tsconfig/` - shared TypeScript base configs (`base.json`, `react-library.json`, `node-library.json`, `nextjs.json`).
- `packages/prettier-config/` - shared Prettier config.

Each shared config package gets:
- Its own `package.json` with correct `main`/`exports` field.
- `README.md` with usage instructions (only if requested).
- Proper version (can be `"0.0.0"` for workspace-only packages).

#### Workspace-aware tool configuration
- ESLint: use `tsconfig.json` project references so type-aware rules work across packages.
- Vitest: workspace config (`vitest.workspace.ts`) defining per-package test setups.
- Knip: workspace-level configuration with per-package entry points.
- Syncpack: enforce consistent dependency versions across all packages.
- Changesets: configure linked/fixed version groups for related packages.

---

### Step 5: Install Dependencies

- Calculate all required dev dependencies from the configs generated.
- Group installs into a single command to avoid repeated lockfile churn.
- Install them with the detected package manager:
  - `npm install -D ...`
  - `pnpm add -D ...`
  - `yarn add -D ...`
  - `bun add -d ...`
- Add scripts to `package.json`:
  **Template:** `templates/package-scripts.json`
  Standard scripts for linting, formatting, typechecking, testing, and husky preparation.
- For monorepos, add root-level scripts that delegate to the task runner (`turbo lint`, `turbo build`, etc.).

---

### Step 6: Config Validation and Testing

After generating configs, validate that they actually work:

1. **Lint check**: Run `eslint .` (or `biome check .`) and confirm it parses without config errors. Fix any issues with the config itself (not pre-existing code issues).
2. **Format check**: Run `prettier --check .` (or `biome format .`) and confirm the formatter can process files.
3. **Type check**: Run `tsc --noEmit` and confirm TypeScript compiles with the new tsconfig. If there are pre-existing errors, report them but do not treat them as config failures.
4. **Build check**: If a build config was generated (Vite, Webpack), run the build and confirm it succeeds.
5. **Hook check**: If git hooks were configured, verify they execute (e.g., `npx lint-staged --diff="HEAD~0"` for a dry run).

**Detect unused config rules:**
- Run `eslint --print-config src/index.ts` and identify rules that are set but never triggered on the codebase.
- For large configs, suggest removing unused rules to reduce lint time.

**Benchmark config performance:**
- Run `TIMING=1 eslint .` and report the slowest rules.
- If any rule takes disproportionate time, suggest moving it to CI-only config or replacing it with a faster alternative.

**Config diffing for upgrades:**
- When updating an existing config, show a diff of what changed before applying.
- Preserve user comments and customizations when merging.

---

### Step 7: Report

**Template:** `templates/report-template.txt`
Example output report showing files created, dependencies installed, scripts added, validation results, and notes.

---

## Config-as-Code Patterns

For organizations that need to share configs across multiple repositories:

### Shared config NPM packages

Generate a publishable config package structure:

```
packages/eslint-config-acme/
  index.js          # Main config (flat config format)
  react.js          # React-specific rules
  node.js           # Node.js-specific rules
  package.json      # { "name": "eslint-config-acme", "main": "index.js" }
```

### Config inheritance and composition

Support layered configuration:
1. **Organization base** - installed via NPM package (`eslint-config-acme`).
2. **Project overrides** - local `eslint.config.js` extends the org base, adds project-specific rules.
3. **Environment overrides** - CI, test, and development environments layer additional rules.

### Programmatic config generation

For complex setups where JSON/JS configs are insufficient:
- Generate factory functions that produce configs based on parameters:
  ```js
  // eslint.config.js
  import { createConfig } from 'eslint-config-acme';
  export default createConfig({
    framework: 'react',
    typescript: true,
    strictness: 'recommended',
    testFramework: 'vitest'
  });
  ```
- This pattern lets organizations ship one config package that adapts to each project's needs.

### Config documentation generation

After generating configs, produce a summary of all active rules and their severity:
- List enabled ESLint rules grouped by category (errors, warnings, off).
- List TypeScript compiler flags that are active and what they enforce.
- List ignored paths and why they are excluded.
- This documentation lives in the config output report, not as a separate file (unless explicitly requested).

---

## Configuration

| Option | Type | Default | Description |
|---|---|---|---|
| `style` | string | `"recommended"` | `"strict"`, `"recommended"`, or `"minimal"` |
| `useBiome` | boolean | `false` | Use Biome instead of ESLint + Prettier |
| `semi` | boolean | `true` | Semicolons in Prettier/Biome |
| `singleQuote` | boolean | `true` | Single quotes in Prettier/Biome |
| `tabWidth` | number | `2` | Indent size |
| `printWidth` | number | `100` | Max line length |
| `endOfLine` | string | `"lf"` | Line endings: `"lf"`, `"crlf"`, `"auto"` |
| `trailingComma` | string | `"es5"` | Trailing commas: `"all"`, `"es5"`, `"none"` |
| `tsStrict` | boolean | `true` | Enable TypeScript strict mode |
| `tsStrictPhase` | number | `4` | Incremental strict mode phase (1-4) |
| `cssFramework` | string | `"tailwind"` | `"tailwind"`, `"css-modules"`, `"styled-components"`, `"none"` |
| `testFramework` | string | `"vitest"` | `"vitest"`, `"jest"`, `"none"` |
| `gitHooks` | string | `"husky"` | `"husky"`, `"lefthook"`, `"none"` |
| `ciProvider` | string | `"github"` | `"github"`, `"gitlab"`, `"none"` |
| `docker` | boolean | `false` | Generate Docker configs |
| `security` | boolean | `false` | Generate security header configs |
| `knip` | boolean | `true` | Generate Knip config for unused export detection |
| `monorepoSharedConfigs` | boolean | `false` | Generate shared config packages in monorepo |
