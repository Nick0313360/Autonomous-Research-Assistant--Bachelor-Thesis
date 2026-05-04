---
name: genskills:git-hooks
description: >
  Set up and manage git hooks with Husky + lint-staged for automated code quality.
  Triggers on: "git hooks", "husky", "lint-staged", "pre-commit hook",
  "commit hook", "pre-push hook".
user-invocable: true
argument-hint: "[action] - e.g., 'setup' or 'add pre-push' or 'remove pre-commit'"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(npm *), Bash(npx *), Bash(pnpm *), Bash(git *)"
genskills-version: "1.2.0"
genskills-category: "workflow"
genskills-depends: []
---

# Git Hooks

Set up and manage git hooks for automated code quality enforcement.

## Process

### Step 0: Load Context
- Check `CLAUDE.md` for existing hook conventions
- Check `${CLAUDE_SKILL_DIR}/_config.json` for preferences

### Step 1: Parse Arguments
Parse `$ARGUMENTS`:
- `setup` - full setup: install Husky + lint-staged + commitlint
- `add <hook>` - add a specific hook (pre-commit, pre-push, commit-msg)
- `remove <hook>` - remove a specific hook
- `list` - show current hooks
- `fix` - fix broken hook setup

### Step 2: Detect Current State
- Check if Husky is already installed (`.husky/` directory)
- Check if lint-staged is configured (package.json or `.lintstagedrc`)
- Check if commitlint is configured (`.commitlintrc`, `commitlint.config.*`)
- Detect package manager (npm, pnpm, yarn, bun)
- Check existing `.git/hooks/` for non-Husky hooks

### Step 3: Setup (if `setup` or no existing hooks)

**Install Husky:**
```bash
npm install -D husky
npx husky init
```

**Install and configure lint-staged:**
```bash
npm install -D lint-staged
```

Add to `package.json`:
```json
{
  "lint-staged": {
    "*.{js,jsx,ts,tsx}": [
      "eslint --fix",
      "prettier --write"
    ],
    "*.{json,md,yml,yaml}": [
      "prettier --write"
    ],
    "*.{css,scss}": [
      "prettier --write"
    ],
    "*.py": [
      "ruff check --fix",
      "ruff format"
    ]
  }
}
```

Tailor lint-staged config to detected tools in the project.

**Install and configure commitlint:**
```bash
npm install -D @commitlint/cli @commitlint/config-conventional
```

Create `commitlint.config.js`:
```js
export default {
  extends: ['@commitlint/config-conventional'],
};
```

### Step 4: Configure Hooks

**pre-commit** (`.husky/pre-commit`):
```bash
npx lint-staged
```

**commit-msg** (`.husky/commit-msg`):
```bash
npx --no -- commitlint --edit $1
```

**pre-push** (`.husky/pre-push`):
```bash
npm run typecheck
npm test
```

Only add hooks that match the project's tooling:
- pre-commit with lint-staged: only if linter/formatter exists
- commit-msg with commitlint: only if user wants conventional commits
- pre-push with tests: only if test runner exists

### Step 5: Verify
- Run a test commit to verify hooks work
- Verify lint-staged processes only staged files
- Check that hooks are executable (Unix permissions)

### Step 6: Report
```
## Git Hooks Configured

### Hooks Installed
- pre-commit - lint-staged (ESLint + Prettier on staged files)
- commit-msg - commitlint (conventional commits)
- pre-push - typecheck + tests

### Dependencies Added
- husky (dev)
- lint-staged (dev)
- @commitlint/cli (dev)
- @commitlint/config-conventional (dev)

### Conventional Commit Format
<type>(<scope>): <description>

Types: feat, fix, docs, style, refactor, perf, test, build, ci, chore

### Notes
- Hooks run automatically on git commit/push
- To bypass (emergency): git commit --no-verify
- To add more hooks: `/genskills:git-hooks add <hook-name>`
```

## Configuration
- `useCommitlint`: boolean - include commitlint setup (default: true)
- `usePrePush`: boolean - include pre-push hook (default: true)
- `lintStagedConfig`: object - custom lint-staged configuration
- `commitTypes`: string[] - allowed commit types (default: conventional)
