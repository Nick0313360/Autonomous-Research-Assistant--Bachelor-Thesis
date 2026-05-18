---
name: genskills:refactor
description: >
  Intelligently refactor code to improve structure, readability, and maintainability
  while preserving behavior. Triggers on: "refactor", "clean up", "restructure", "simplify".
user-invocable: true
argument-hint: "[file or function] [--type extract|simplify|rename|dedup|modernize] [--scope minimal|moderate|aggressive]"
allowed-tools: "Read, Edit, Grep, Glob, Bash(git diff*), Bash(git stash*), Bash(npm test*), Bash(npm run*), Bash(npx vitest*), Bash(npx jest*), Bash(npx tsc*), Bash(pytest*), Bash(cargo test*)"
genskills-version: "1.3.0"
genskills-category: "code-quality"
genskills-depends: []
---

# Refactor

Improve code structure and quality without changing behavior.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow coding conventions and patterns documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)

### Step 1: Parse Arguments & Understand Code
Parse `$ARGUMENTS`:
- First positional: target file or function name to refactor
- `--type`: specific refactoring type - "extract" | "simplify" | "rename" | "dedup" | "modernize" | "decouple"
- `--scope`: how far to take it - "minimal" | "moderate" | "aggressive" (default: "moderate")
- `--dry-run`: show proposed changes without applying

If no target specified, ask the user what to refactor.

**Understand the code:**
- Read the target file/function completely
- Map the dependency chain - what calls this code (`Grep` for function name) and what it calls
- Identify all callers and consumers of the public API being refactored
- Check for related types, interfaces, and test files
- **Run existing tests first** to establish a green baseline:
  ```bash
  npm test          # or npx vitest run / npx jest / pytest / cargo test
  ```
  If tests fail before refactoring, stop and report.

### Step 2: Identify Refactoring Opportunities
Analyze the code for these patterns (filtered by `--type` if specified):

**Extract Method** (`--type extract`):
- Long functions (>40 lines) that do multiple distinct things
- Repeated inline logic that could be a named function
- Complex conditional bodies that deserve their own function
- Callback/handler bodies that are hard to read inline

**Reduce Complexity** (`--type simplify`):
- Deeply nested conditionals (>3 levels) - flatten with early returns/guard clauses
- High cyclomatic complexity - break into smaller functions
- Complex boolean expressions - extract into named variables or functions
- Switch statements with many cases - consider lookup objects or strategy pattern
- Unnecessary ternary nesting - simplify or use if/else
- Redundant null checks when optional chaining suffices

**Improve Naming** (`--type rename`):
- Variables/functions with unclear names that don't convey intent
- Single-letter variables outside of trivial loops
- Misleading names (e.g., `data` for a specific user record)
- Inconsistent naming conventions within the file
- Boolean variables without is/has/should prefix

**Remove Duplication** (`--type dedup`):
- Repeated code patterns across files (3+ occurrences)
- Copy-pasted logic with minor variations - extract shared function with parameters
- Similar component structures - extract shared component with props
- Duplicate type definitions - consolidate into shared types

**Modernize Patterns** (`--type modernize`):
- `var` → `const`/`let`
- Callbacks → async/await
- `_.map`/`_.filter` → native array methods
- `require()` → `import`
- Class components → function components with hooks (React)
- `moment` → `dayjs` or `date-fns`
- String concatenation → template literals
- `arguments` → rest parameters
- `for...in` on arrays → `for...of` or array methods
- `new Promise((resolve) => ...)` wrapping an async call → just await

**Reduce Coupling** (`--type decouple`):
- Circular dependencies between modules
- God objects/files that do too many things
- Tight coupling to specific implementations - extract interfaces
- Direct dependency on external services - add abstraction layer
- Hard-coded configuration - extract to config/env

### Step 3: Plan and Confirm
Before applying changes, report the plan:
```
## Refactoring Plan

### Target: src/services/userService.ts

### Proposed Changes
1. Extract `validateUserInput()` from `createUser()` (lines 45-82)
2. Extract `sendWelcomeEmail()` from `createUser()` (lines 95-120)
3. Simplify nested conditionals in `updateUser()` with guard clauses
4. Rename `data` → `userRecord` for clarity (12 occurrences)

### Impact
- 4 files will be modified
- Public API unchanged
- ~30 lines net reduction

Proceed? (y/n)
```

### Step 4: Apply Refactoring
- Make changes incrementally - one refactoring type at a time
- Preserve exact behavior (no feature additions or removals)
- Keep the same public API unless explicitly asked to change it
- Ensure all imports, references, and re-exports are updated
- Update related type definitions if applicable
- Do NOT add comments, docstrings, or type annotations to code you didn't change

**Execution order:**
1. Extract/create new functions or modules
2. Update callers to use new extractions
3. Apply simplifications and modernizations
4. Clean up imports and unused code
5. Update re-exports if needed

### Step 5: Verify
After all changes:
1. **Run tests** - all tests that passed before MUST still pass
   ```bash
   npm test    # or equivalent
   ```
2. **Type check** (if TypeScript/typed language):
   ```bash
   npx tsc --noEmit
   ```
3. **Show diff summary**: `git diff --stat`
4. **List any potential behavior changes** (there should be none)

If tests fail after refactoring:
- Identify the failing test and the cause
- Fix if the failure is due to an import/reference issue
- Revert if the failure indicates a behavior change
- Re-verify after fix

### Step 6: Report
```
## Refactoring Summary

### Changes Made
- [file:line] Description of refactoring applied

### Metrics
| Metric | Before | After |
|---|---|---|
| Lines of code | N | N |
| Functions | N | N |
| Max function length | N lines | N lines |
| Max nesting depth | N | N |
| Duplicated patterns | N | N |

### Verification
- Tests: ✓ all passing (N tests)
- Type check: ✓ 0 errors
- Behavior changes: none

### Follow-up Suggestions
- Additional refactoring opportunities found but not applied (out of scope)
- Run `/genskills:test-generator` if test coverage is insufficient
- Run `/genskills:dead-code` to find code orphaned by this refactoring
```

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `maxFunctionLength`: number - threshold for "too long" (default: 40 lines)
- `preserveComments`: boolean - whether to keep existing comments during restructuring (default: true)
- `scope`: "minimal" | "moderate" | "aggressive" - default refactoring scope
- `requireTests`: boolean - abort if no tests exist for the target code (default: false)
- `confirmBeforeApply`: boolean - show plan and wait for confirmation (default: true)
