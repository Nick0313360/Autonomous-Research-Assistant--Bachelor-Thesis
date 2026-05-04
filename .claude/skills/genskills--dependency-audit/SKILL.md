---
name: genskills:dependency-audit
description: >
  Audit project dependencies for unused packages, outdated versions, duplicates,
  license conflicts, and bundle size impact. Triggers on: "check dependencies",
  "audit packages", "unused deps", "dependency audit", "outdated packages".
user-invocable: true
argument-hint: "[scope: all|unused|outdated|licenses|size|security] [--fix] [--monorepo]"
allowed-tools: "Read, Grep, Glob, Bash(npm *), Bash(npx *), Bash(pip *), Bash(yarn *), Bash(pnpm *), Bash(bun *), Bash(cargo *), Bash(go *)"
genskills-version: "1.3.0"
genskills-category: "code-quality"
genskills-depends: []
---

# Dependency Audit

Comprehensive dependency analysis and cleanup.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any dependency policies documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)

### Step 1: Detect Package Manager & Environment
Check for (in order):
- `bun.lockb` → Bun
- `pnpm-lock.yaml` → pnpm
- `yarn.lock` → Yarn (check `.yarnrc.yml` for Yarn 2+/Berry)
- `package-lock.json` → npm
- `requirements.txt` / `pyproject.toml` / `poetry.lock` / `uv.lock` → Python (pip/poetry/uv)
- `Cargo.toml` / `Cargo.lock` → Rust (cargo)
- `go.mod` / `go.sum` → Go

Also detect:
- Monorepo setup: multiple `package.json` files, `workspaces` field, `turbo.json`, `nx.json`, `lerna.json`
- Lock file freshness: `git log -1 --format=%cr -- <lockfile>`

### Step 2: Parse Arguments
Parse `$ARGUMENTS`:
- `all` - run every audit (default)
- `unused` - find unused dependencies only
- `outdated` - check for outdated packages only
- `licenses` - license compliance only
- `size` - bundle size analysis only
- `security` - vulnerability scan only
- `--fix` - automatically remove unused deps and apply safe updates
- `--monorepo` - audit all workspace packages

### Step 3: Run Audits

**Unused Dependencies:**
- Cross-reference `dependencies` and `devDependencies` in package.json with actual imports
- Use Grep to find `import ... from '<pkg>'` or `require('<pkg>')` patterns
- Check for dynamic imports: `import('<pkg>')`, `require.resolve('<pkg>')`
- Check `peerDependencies` - these are expected to be provided by consumers, not imported
- **Do NOT flag:**
  - Packages only used in config files (babel plugins, eslint plugins, postcss plugins, vite plugins)
  - Packages used as CLI tools in `scripts` (package.json scripts section)
  - `@types/*` packages - check if the corresponding package is used instead
  - Packages referenced in framework config (next.config.js, tailwind.config.js, etc.)
  - PostCSS/Babel/SWC plugins configured in config files
  - Packages used via `npx` in scripts
- For monorepos, check usage across all workspace packages before flagging

**Outdated Packages:**
```bash
npm outdated --json        # or pnpm outdated --json / yarn outdated --json / bun outdated
```
- Categorize updates:

| Category | Risk | Action |
|---|---|---|
| **Patch** (1.0.0 → 1.0.1) | Low | Safe to update |
| **Minor** (1.0.0 → 1.1.0) | Low-Medium | Usually safe, check changelog |
| **Major** (1.0.0 → 2.0.0) | High | Breaking changes likely |
| **Deprecated** | Critical | Must migrate |

- For major updates, check the package's CHANGELOG or release notes for breaking changes
- Flag packages > 2 major versions behind as critical

**Security Vulnerabilities:**
```bash
npm audit --json           # or pnpm audit / yarn audit / pip audit / cargo audit
```
- Categorize by severity: critical, high, moderate, low
- Distinguish production vs. dev dependency vulnerabilities
- Suggest specific fix commands where available
- For unfixable vulnerabilities, suggest alternatives or overrides

**Duplicate Packages:**
```bash
npm ls --all 2>/dev/null | grep -E "deduped|invalid"
```
- Check for multiple versions of the same package in the dependency tree
- Identify which top-level deps pull in conflicting versions
- Suggest `overrides` (npm), `resolutions` (yarn), or `pnpm.overrides` to deduplicate

**License Compliance:**
- Extract license field from each dependency's `package.json` (or `Cargo.toml`, `go.mod`)
- Classify licenses:

| Category | Licenses | Risk |
|---|---|---|
| **Permissive** | MIT, ISC, BSD-2, BSD-3, Apache-2.0 | Low |
| **Weak Copyleft** | LGPL, MPL-2.0 | Medium - review usage |
| **Strong Copyleft** | GPL-2.0, GPL-3.0, AGPL-3.0, SSPL | High - may require disclosure |
| **No License** | UNLICENSED, no field | High - legal risk |

- Flag strong copyleft in production dependencies
- Note: devDependencies have less restrictive license requirements

**Bundle Size Impact:**
- Identify heaviest dependencies by install/bundle size
- Suggest lighter alternatives:

| Heavy Package | Lighter Alternative | Savings |
|---|---|---|
| `moment` | `dayjs` or `date-fns` | ~95% smaller |
| `lodash` | `lodash-es` (tree-shake) or native methods | ~90% smaller |
| `axios` | native `fetch` | 100% (built-in) |
| `uuid` | `crypto.randomUUID()` | 100% (built-in) |
| `chalk` | `picocolors` | ~90% smaller |
| `express` | `fastify` or `hono` | Varies |
| `node-fetch` | native `fetch` (Node 18+) | 100% (built-in) |
| `dotenv` | `--env-file` flag (Node 20+) | 100% (built-in) |

- Flag dependencies that are imported but only a small portion is used (tree-shaking opportunity)

### Step 4: Generate Report
```
## Dependency Audit Report

### Security Vulnerabilities
- [CRITICAL] package@version - description - fix: `npm audit fix` or specific command
- [HIGH] package@version - description - fix: manual upgrade required

### Unused Dependencies (safe to remove)
- package - no imports found - `npm uninstall package`

### Outdated - Breaking Changes (major)
- package: current → latest (breaking: migration guide link)

### Outdated - Safe to Update (minor/patch)
- package: current → latest

### Deprecated Packages
- package - deprecated since <date> - recommended alternative: <pkg>

### Duplicates
- package: v1 (via dep-a), v2 (via dep-b) - add override/resolution

### License Concerns
- package - GPL-3.0 - in production deps - requires legal review

### Bundle Size Opportunities
- package (Xkb) → alternative (Ykb) - estimated savings: Z%

### Recommended Actions (copy-paste ready)
1. `npm uninstall <unused packages>`
2. `npm update` (safe minor/patch updates)
3. `npm audit fix` (security fixes)
4. Review: <major-updates> for breaking changes

### Summary
- Dependencies: N total (N prod, N dev)
- Unused: N (estimated N KB savings)
- Outdated: N major, N minor, N patch
- Vulnerabilities: N critical, N high, N moderate
- License issues: N
```

### Step 5: Auto-fix (if --fix)
If `--fix` flag:
```bash
npm uninstall <unused-packages>       # Remove unused
npm update                             # Apply safe minor/patch updates
npm audit fix                          # Fix known vulnerabilities
```
- Only remove high-confidence unused packages
- Only apply patch/minor updates (never auto-apply major)
- Re-run audit after fixes to verify
- Report what was changed

### Step 6: Follow-up
- Suggest `/genskills:security-audit` if critical vulnerabilities found
- Suggest `/genskills:migrate` for major version upgrades with breaking changes
- Suggest `/genskills:dead-code` to find unused code from removed dependencies

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `scope`: "all" | "unused" | "outdated" | "licenses" | "size" | "security" - default audit scope
- `ignorePaths`: string[] - paths to skip when checking imports
- `ignorePackages`: string[] - packages to skip in unused check
- `licenseAllowlist`: string[] - allowed license types (default: MIT, ISC, BSD, Apache-2.0)
- `autoFix`: boolean - auto-remove unused and apply safe updates (default: false)
- `bundleSizeThreshold`: number - flag packages larger than N KB (default: 100)
