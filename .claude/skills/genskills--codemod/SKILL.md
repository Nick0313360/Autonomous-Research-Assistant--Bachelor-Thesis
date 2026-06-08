---
name: genskills:codemod
description: >
  Create and run codemods for large-scale code transformations across the codebase.
  Triggers on: "codemod", "code transform", "bulk rename", "mass refactor",
  "find and replace code", "update all usages".
user-invocable: true
argument-hint: "[transformation] - e.g., 'rename UserService to AuthService' or 'convert class components to hooks'"
allowed-tools: "Read, Edit, Grep, Glob, Bash(npx jscodeshift*), Bash(npx tsc*), Bash(npm test*), Bash(git diff*), Bash(git stash*)"
genskills-version: "1.3.0"
genskills-category: "code-quality"
genskills-depends: []
---

# Codemod

Create and run large-scale code transformations safely.

## Process

### Step 0: Load Context
- Check `CLAUDE.md` for codebase conventions
- Check `${CLAUDE_SKILL_DIR}/_config.json` for preferences

### Step 1: Understand the Transformation
Parse `$ARGUMENTS` to understand what needs to change:

Common transformation types:
1. **Rename** - rename a symbol (function, class, type, variable) across the codebase
2. **API Migration** - update function signatures, add/remove parameters
3. **Pattern Replacement** - convert one code pattern to another
4. **Import Rewrite** - change import paths or package names
5. **Syntax Modernization** - callbacks→promises, var→const, class→function, etc.
6. **Framework Migration** - convert between frameworks or major versions

### Step 2: Assess Impact
Before making any changes:
- Search for all occurrences of the target pattern
- Count affected files and lines
- Identify edge cases: string references, comments, dynamic usage
- Check for type-level references (interfaces, type aliases, generics)
- Report scope to user:
  ```
  Found 47 occurrences across 23 files.
  - 31 direct usages
  - 12 type references
  - 4 string/comment references
  Proceed? (y/n)
  ```

### Step 3: Plan Transformation
Define the transformation rules:

**For renames:**
- Source symbol → Target symbol
- Update: imports, declarations, usages, type references, JSX, strings in test descriptions
- Preserve casing variants: `UserService` → `AuthService`, `userService` → `authService`, `USER_SERVICE` → `AUTH_SERVICE`
- Update file names if they match the symbol

**For API migrations:**
- Old signature → New signature
- Parameter mapping (reorder, rename, add defaults, remove)
- Return type changes
- Update all call sites

**For pattern replacements:**
- Before pattern → After pattern
- Handle variations (with/without optional parts)

### Step 4: Execute Transformation

**Prefer jscodeshift** for AST-aware transforms in JS/TS:
```bash
npx jscodeshift -t transform.ts --extensions=ts,tsx src/
```

**For simpler transforms**, use targeted Edit operations:
1. Find all files containing the pattern
2. For each file, make the replacement with full context awareness
3. Handle imports: add new imports, remove unused old imports
4. Process files in dependency order (types first, then implementations, then tests)

**Execution order:**
1. Type definitions and interfaces
2. Implementation files
3. Re-exports and barrel files
4. Test files
5. Documentation and comments
6. Config files (if applicable)

### Step 5: Verify

After all changes:
1. **Type check**: `npx tsc --noEmit` - must pass with zero errors
2. **Lint**: run project linter - fix any new violations
3. **Test**: `npm test` - all tests must pass
4. **Search**: grep for any remaining old pattern - should be zero
5. **Diff review**: `git diff --stat` - verify only expected files changed

If verification fails:
- Identify the failing file/test
- Fix the issue (likely an edge case missed)
- Re-verify

### Step 6: Report
```
## Codemod Complete

### Transformation
<description of what changed>

### Impact
- <N> files modified
- <N> occurrences transformed
- <N> imports updated
- <N> type references updated

### Verification
- ✓ TypeScript: 0 errors
- ✓ Lint: passed
- ✓ Tests: <N> passed, 0 failed
- ✓ No remaining old pattern references

### Changes by Directory
- src/services/ - 8 files
- src/components/ - 12 files
- tests/ - 6 files

### Review
Run `git diff` to review all changes before committing.
```

## Configuration
- `dryRun`: boolean - report changes without applying (default: false)
- `excludePaths`: string[] - paths to exclude
- `includeTests`: boolean - transform test files too (default: true)
- `includeComments`: boolean - update comments/strings (default: false)
