---
name: genskills:monorepo
description: >
  Navigate and manage monorepo tooling - Turborepo, Nx, Lerna, pnpm workspaces.
  Triggers on: "which packages changed", "run tests for affected", "add workspace",
  "monorepo", "workspace".
user-invocable: true
argument-hint: "[action: affected|add|deps|graph] [package name]"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(npx turbo *), Bash(npx nx *), Bash(npx lerna *), Bash(pnpm *), Bash(npm *), Bash(yarn *), Bash(git *)"
genskills-version: "1.1.0"
genskills-category: "workflow"
genskills-depends: []
---

# Monorepo Management

Navigate and manage monorepo workspaces effectively.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any monorepo conventions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Detect the default branch for comparison

### Step 1: Detect Monorepo Tool
Check for (in priority order):
- `turbo.json` → Turborepo
- `nx.json` → Nx
- `lerna.json` → Lerna
- `pnpm-workspace.yaml` → pnpm workspaces
- `package.json` "workspaces" field → npm/yarn workspaces
- Identify the package scope (e.g., `@scope/`) from existing packages

### Step 2: Execute Action
Parse `$ARGUMENTS` for action:

**affected** (default):
- Determine what changed: `git diff --name-only <default-branch>...HEAD`
- Map changed files to affected packages (match file paths to workspace directories)
- Resolve transitive dependents - packages that depend on changed packages
- List affected packages with their dependency chains
- Suggest the correct run command for the detected tool

**add**:
- Parse `$1` as the new package name
- Create new workspace package with correct structure matching existing packages
- Add to workspace configuration (pnpm-workspace.yaml, turbo.json pipeline, etc.)
- Set up `package.json` with correct name, version, and shared dependencies
- Wire up shared configs: tsconfig, eslint, prettier, etc.
- Add to CI if per-package CI exists

**deps**:
- Show inter-package dependency graph
- Identify circular dependencies (these are always bugs in a monorepo)
- Show which packages depend on a given package (reverse dependency tree)
- Flag version mismatches of shared external deps across packages

**graph**:
- Display the task/package dependency graph using the tool's native command
- Show build order (topological sort)
- Identify bottlenecks in the graph (packages with many dependents)

### Step 3: Report
```
## Monorepo Status

### Tool: Turborepo / Nx / etc.
### Packages: N total

### Affected Packages (since <default-branch>)
- @scope/package-a (direct change - 5 files modified)
- @scope/package-b (depends on package-a)

### Run Commands (copy-paste ready)
- Test affected: `npx turbo run test --filter=...[<default-branch>]`
- Build affected: `npx turbo run build --filter=...[<default-branch>]`
- Lint affected: `npx turbo run lint --filter=...[<default-branch>]`

### Issues Found
- Circular dependencies (if any)
- Version mismatches (if any)
```

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `baseBranch`: string - branch to compare against for affected (default: auto-detect)
- `scope`: string - package scope prefix (e.g., "@myorg")
- `packageTemplate`: string - path to template for new packages
