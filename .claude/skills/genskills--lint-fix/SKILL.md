---
name: genskills:lint-fix
description: >
  Detect and auto-fix linting issues across your codebase using ESLint, Prettier,
  Biome, Ruff, or other configured linters. Triggers on: "fix lint", "lint fix",
  "format code", "fix formatting", "fix style issues".
user-invocable: true
argument-hint: "[file or directory] [--staged] [--check-only]"
allowed-tools: "Read, Edit, Grep, Glob, Bash(npx eslint*), Bash(npx prettier*), Bash(npx biome*), Bash(npx oxlint*), Bash(npm run*), Bash(ruff*), Bash(black*), Bash(isort*), Bash(cargo fmt*), Bash(cargo clippy*), Bash(gofmt*), Bash(golangci-lint*), Bash(git diff*)"
genskills-version: "1.3.0"
genskills-category: "code-quality"
genskills-depends: []
---

# Lint Fix

Detect and fix linting and formatting issues.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any linting conventions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Check `package.json` for custom lint scripts (`lint`, `lint:fix`, `format`, `check`)

### Step 1: Detect Linting Tools
Check the project for configured tools (in priority order):

**JavaScript/TypeScript:**

| Tool | Config Files | Command |
|---|---|---|
| **Biome** | `biome.json`, `biome.jsonc` | `npx biome check --fix` |
| **ESLint** | `eslint.config.*` (flat), `.eslintrc.*` (legacy) | `npx eslint --fix` |
| **Prettier** | `.prettierrc*`, `prettier` in package.json | `npx prettier --write` |
| **oxlint** | `.oxlintrc.json` | `npx oxlint --fix` |
| **deno lint** | `deno.json` | `deno lint --fix` |

**Python:**

| Tool | Config | Command |
|---|---|---|
| **Ruff** | `ruff.toml`, `[tool.ruff]` in pyproject.toml | `ruff check --fix && ruff format` |
| **Black** | `[tool.black]` in pyproject.toml | `black .` |
| **isort** | `[tool.isort]` in pyproject.toml | `isort .` |
| **flake8** | `.flake8`, `[tool.flake8]` | `flake8` (no auto-fix) |
| **mypy** | `mypy.ini`, `[tool.mypy]` | See type-check skill |

**Rust:**
- `rustfmt.toml` → `cargo fmt`
- clippy → `cargo clippy --fix`

**Go:**
- `gofmt` / `goimports` → `gofmt -w .`
- `golangci-lint` → `golangci-lint run --fix`

**Other:**
- `.editorconfig` → EditorConfig settings (inform formatting)
- Custom lint scripts in `package.json` (prefer these over direct tool invocation)

### Step 2: Determine Scope
Parse `$ARGUMENTS`:
- First positional: file or directory to lint
- `--staged`: only lint staged files (`git diff --cached --name-only --diff-filter=ACMR`)
- `--check-only`: report issues without fixing (dry run)
- `--changed`: lint files changed since last commit

If no arguments, lint the full project.

### Step 3: Run Linters
**Order matters - run in this sequence:**

1. **Linters with auto-fix first** (they fix logic/pattern issues):
   - ESLint/Biome/oxlint/Ruff with `--fix`
   - Clippy with `--fix`
2. **Formatters second** (their output is canonical for style):
   - Prettier/Biome format/Black/Ruff format
   - `cargo fmt` / `gofmt`
3. **Import sorting** (if separate from linter):
   - isort (Python) / ESLint import sorting

**Prefer project scripts:**
```bash
# Check for and prefer these over direct invocation:
npm run lint:fix    # or lint --fix
npm run format      # or prettier --write
```

If scripts don't exist, fall back to direct tool invocation.

Capture all output - distinguish between:
- Auto-fixed issues (resolved by `--fix`)
- Remaining issues requiring manual intervention
- Formatting changes applied

### Step 4: Fix Remaining Issues Manually
For issues that auto-fix can't resolve:
- Read the flagged files and understand the lint rule violation
- Apply manual fixes following the project's lint configuration
- Common manual fixes:
  - Unused imports/variables (remove if truly unused, not if used dynamically)
  - Complex unused expressions (simplify or restructure)
  - Accessibility issues flagged by eslint-plugin-jsx-a11y
  - Naming convention violations
  - Complexity warnings (break up functions)
  - Type-related lint issues (defer to `/genskills:type-check`)

**Rules for manual fixes:**
- Do NOT add `// eslint-disable` comments unless the rule is genuinely wrong for that line
- Do NOT disable rules project-wide to fix violations
- If a rule is consistently wrong, note it in the report for the user to decide
- Preserve existing `eslint-disable` comments - don't remove them without understanding why

### Step 5: Re-run and Verify
```bash
# Run linter again in check mode (no --fix) to confirm clean
npx eslint .                    # should report 0 errors
npx prettier --check .          # should report 0 changes needed
```

If issues remain after manual fixes, report them clearly with the rule name and reason.

### Step 6: Report
```
## Lint Fix Report

### Tools Used
- ESLint v9.x (flat config) - 0 errors, 0 warnings
- Prettier v3.x - all files formatted
- (or Biome v1.x - lint + format clean)

### Auto-fixed (by linter --fix)
- N issues auto-fixed across M files
- Top rules fixed: no-unused-vars (5), import/order (12), ...

### Manually Fixed
- [file:line] Rule: description - what was changed and why

### Formatting Changes
- N files reformatted by Prettier/Biome/Black

### Remaining (requires manual attention)
- [file:line] Rule: description - why it can't be auto-fixed
- [file:line] Rule: description - needs architectural decision

### Summary
| Metric | Count |
|---|---|
| Total issues found | N |
| Auto-fixed | N |
| Manually fixed | N |
| Formatting changes | N files |
| Remaining | N |

### Follow-up
- Run `/genskills:type-check` if type-related lint issues remain
- Run `/genskills:code-review` to verify fixes don't change behavior
```

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `preferScript`: boolean - prefer `npm run lint:fix` over direct tool invocation (default: true)
- `ignorePaths`: string[] - paths to skip
- `formatOnFix`: boolean - also run formatter after linting (default: true)
- `stagedOnly`: boolean - default to only linting staged files (default: false)
- `maxWarnings`: number - fail if more than N warnings remain (default: unlimited)
