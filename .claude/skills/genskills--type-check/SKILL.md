---
name: genskills:type-check
description: >
  Run type checking and fix type errors in TypeScript, Python (mypy/pyright),
  or other typed languages. Triggers on: "type check", "fix types", "fix type errors",
  "tsc errors", "mypy errors".
user-invocable: true
argument-hint: "[file or directory] [--strict] [--install-types]"
allowed-tools: "Read, Edit, Grep, Glob, Bash(npx tsc*), Bash(npm run*), Bash(npm install*), Bash(mypy*), Bash(pyright*), Bash(pip install*), Bash(cargo check*), Bash(go vet*)"
genskills-version: "1.3.0"
genskills-category: "code-quality"
genskills-depends: []
---

# Type Check

Run type checking and resolve type errors.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any type-checking conventions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Check `package.json` for custom type-check scripts (`type-check`, `typecheck`, `tsc`, `check`)

### Step 1: Parse Arguments & Detect Type System
Parse `$ARGUMENTS`:
- First positional: file or directory to check
- `--strict`: enforce strict type checking even if not configured
- `--install-types`: automatically install missing `@types/*` packages
- `--changed`: only check recently changed files

**Detect type system (in order):**

| Config | Type System | Command |
|---|---|---|
| Custom script in package.json | Use project script | `npm run type-check` / `npm run typecheck` |
| `tsconfig.json` | TypeScript | `npx tsc --noEmit` |
| `mypy.ini` or `[tool.mypy]` | mypy | `mypy .` |
| `pyrightconfig.json` or `[tool.pyright]` | pyright | `pyright` |
| `Cargo.toml` | Rust | `cargo check` |
| `go.mod` | Go | `go vet ./...` |

Also check:
- Strict mode settings (`strict: true` in tsconfig, `strict = true` in mypy)
- Path aliases (`paths` in tsconfig, `baseUrl`)
- Project references (`references` in tsconfig for monorepos)
- Multiple tsconfig files (tsconfig.json, tsconfig.build.json, tsconfig.node.json)

### Step 2: Run Type Checker
```bash
# Prefer project scripts
npm run type-check 2>&1        # or npm run typecheck

# Fallback to direct invocation
npx tsc --noEmit 2>&1          # TypeScript
mypy . 2>&1                    # Python mypy
pyright 2>&1                   # Python pyright
cargo check 2>&1               # Rust
go vet ./... 2>&1              # Go
```

If `$ARGUMENTS` specified a file/directory:
- TypeScript: `npx tsc --noEmit` checks full project (can't scope to single file), but filter output
- mypy/pyright: can target specific paths
- Rust/Go: can target specific packages

**Parse error output into structured list:**
- File path
- Line number
- Error code (TS2345, TS2339, E0308, etc.)
- Error message
- Group errors by category for systematic fixing

### Step 3: Fix Type Errors
Fix errors in dependency order (upstream fixes often resolve downstream errors):

**Priority 1 - Module Resolution:**
- Fix import paths: wrong relative path, missing extension, path alias misconfiguration
- Install missing `@types/*` packages:
  ```bash
  npm install -D @types/node @types/react @types/express  # etc.
  ```
- Add `declare module` for untyped third-party modules (as last resort)
- Fix tsconfig `paths` and `baseUrl` mismatches

**Priority 2 - Missing Types:**
- Add type annotations to function parameters and return types
- Import missing type definitions from libraries
- Create type definitions for untyped modules/data
- Add generic type parameters where inferred types are too broad

**Priority 3 - Type Mismatches:**
- Fix actual type errors in logic (wrong argument type, incompatible assignment)
- Add proper type guards for union types:
  ```typescript
  if (typeof value === 'string') { ... }
  if ('property' in obj) { ... }
  if (value instanceof Error) { ... }
  ```
- Use discriminated unions instead of type assertions
- Fix return type mismatches (function returns different type than declared)

**Priority 4 - Null/Undefined Errors:**
- Add null checks with early returns (guard clauses)
- Use optional chaining (`?.`) where appropriate
- Use nullish coalescing (`??`) for default values
- Avoid non-null assertions (`!`) - use type guards instead
- Handle `undefined` from `Array.find()`, `Map.get()`, optional properties

**Priority 5 - Generics:**
- Fix generic type parameters and constraints
- Add explicit generic arguments when inference fails
- Fix generic function calls with wrong type arguments

**Priority 6 - Strict Mode Issues:**
- Replace `any` with specific types or `unknown`
- Add explicit return types to functions
- Handle implicit `any` from untyped dependencies
- Fix `noImplicitReturns` violations (missing return in branches)
- Fix `strictNullChecks` violations

**Rules:**
- Never use `// @ts-ignore` or `// @ts-expect-error` unless the error is genuinely a false positive in a typed dependency
- Prefer `unknown` over `any` when the type is truly unknown
- Add type guards instead of type assertions (`as`) where possible
- Do NOT add type annotations to code you didn't change (unless it's causing the error)
- If a type error reveals an actual bug, fix the bug, don't just fix the types
- Prefer narrowing (`if` checks, `instanceof`) over casting (`as`)

### Step 4: Re-run and Verify
```bash
npx tsc --noEmit 2>&1    # Should report 0 errors
```

If new errors appeared from fixes:
- These are usually downstream effects - fix them too
- Iterate up to 3 times
- If an error requires architectural changes, flag it for manual review

Also run test suite to ensure type fixes didn't break behavior:
```bash
npm test                  # Verify no behavior regressions
```

### Step 5: Report
```
## Type Check Report

### Type System
- TypeScript v5.x with strict mode: enabled/disabled
- tsconfig: <path> (N files in scope)

### Errors Fixed
| Error Code | Description | Files | Fix Applied |
|---|---|---|---|
| TS2345 | Argument type mismatch | 3 | Added type guard |
| TS2339 | Property doesn't exist | 2 | Added interface property |
| TS7006 | Implicit any parameter | 5 | Added type annotations |

### Packages Installed
- @types/node - resolve Node.js API types
- @types/express - resolve Express types

### Remaining Errors (requires manual review)
- [file:line] TS2322 - complex generic constraint, needs architectural decision
- [file:line] TS2345 - API response type doesn't match runtime data (possible API contract issue)

### Summary
| Metric | Count |
|---|---|
| Total errors found | N |
| Auto-fixed | N |
| Types installed | N packages |
| Remaining | N |

### Recommendations
- Enable `strict: true` in tsconfig for stronger guarantees
- Add `noUncheckedIndexedAccess` for safer array/object access
- Run `/genskills:lint-fix` to clean up formatting from type changes
- Consider `/genskills:code-review` to verify type fixes are semantically correct
```

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `preferScript`: boolean - prefer `npm run type-check` over direct `tsc` (default: true)
- `strictMode`: boolean - enforce strict type checking even if not configured (default: false)
- `autoInstallTypes`: boolean - automatically install missing @types packages (default: true)
- `maxIterations`: number - max fix-and-recheck cycles (default: 3)
- `fixStrategy`: "safe" | "aggressive" - safe avoids any casts, aggressive fixes more (default: "safe")
