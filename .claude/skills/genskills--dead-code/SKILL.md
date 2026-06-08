---
name: genskills:dead-code
description: >
  Find and remove dead code - unused exports, unreachable branches, unused variables, orphan files.
  Triggers on: "dead code", "unused code", "find unused", "remove dead code",
  "orphan files", "unused exports".
user-invocable: true
argument-hint: "[scope] - e.g., 'src/' or 'full' or 'exports-only'"
allowed-tools: "Read, Edit, Grep, Glob, Bash(npx ts-prune*), Bash(npx knip*), Bash(npx unimported*), Bash(npm *), Bash(git log*)"
genskills-version: "1.3.0"
genskills-category: "code-quality"
genskills-depends: []
---

# Dead Code

Find and safely remove dead code from the codebase.

## Process

### Step 0: Load Context
- Check `CLAUDE.md` for any known dead code exceptions or keep-alive patterns
- Check `${CLAUDE_SKILL_DIR}/_config.json` for preferences

### Step 1: Parse Arguments
Parse `$ARGUMENTS`:
- `$0` = scope: directory path, "full" (entire project), or analysis type
- `--dry-run` - report only, don't remove anything (default behavior)
- `--fix` - actually remove dead code
- `--aggressive` - include possibly-dead code (dynamic imports, reflection)

Analysis types: `exports-only`, `files-only`, `variables-only`, `full`

### Step 2: Use Existing Tools (if available)
Check for and prefer established tools:

1. **knip** - comprehensive dead code finder for JS/TS
   - `npx knip` - finds unused files, dependencies, exports, types
2. **ts-prune** - finds unused TypeScript exports
   - `npx ts-prune`
3. **unimported** - finds unimported files
   - `npx unimported`

If tools are available, run them and parse results. Otherwise, proceed with manual analysis.

### Step 3: Manual Analysis

**3a. Orphan Files** - files with no importers:
- Build import graph from all source files
- For each file, check if any other file imports it
- Exclude entry points (index.ts, main.ts, pages/*, app/*, test files, config files)
- Flag files with zero importers

**3b. Unused Exports** - exported symbols nobody imports:
- For each export in each file, search for imports of that symbol
- Check re-exports in barrel files (index.ts)
- Account for dynamic imports: `import()`, `require()`
- Check if exported for external package consumers (skip if in `main`/`exports` of package.json)

**3c. Unused Variables/Functions** - within-file dead code:
- Functions/classes defined but never called within the file and not exported
- Variables assigned but never read
- Unreachable code after return/throw/break/continue
- Empty catch blocks, useless conditions (`if (true)`)

**3d. Unused Dependencies** - packages installed but never imported:
- Cross-reference package.json dependencies with actual imports
- Check for CLI usage (scripts in package.json)
- Check for implicit usage (PostCSS plugins, Babel presets, type packages)

### Step 4: Classify Results

Classify each finding by confidence:

| Confidence | Meaning | Action |
|---|---|---|
| **High** | Definitely dead - no references anywhere | Safe to remove |
| **Medium** | Probably dead - only referenced in dead code | Remove if parent is removed |
| **Low** | Possibly dead - could be used dynamically | Flag for review |

Skip known patterns that appear dead but aren't:
- Decorator-referenced classes
- Dependency injection tokens
- Event handler registrations
- Framework convention files (middleware.ts, layout.tsx)
- Test utilities and fixtures

### Step 5: Report (dry-run) or Remove (--fix)

**Dry-run report:**
```
## Dead Code Analysis

### Summary
- 12 orphan files (no importers)
- 34 unused exports
- 8 unused dependencies
- ~450 lines of removable code

### High Confidence (safe to remove)
#### Orphan Files
- src/utils/old-helper.ts - last modified 6 months ago, 0 importers
- src/components/DeprecatedBanner.tsx - 0 importers

#### Unused Exports
- src/api/client.ts: `formatLegacyResponse` - 0 import sites
- src/utils/math.ts: `roundToNearest` - 0 import sites

#### Unused Dependencies
- lodash - 0 imports found (use native methods)
- moment - 0 imports found

### Medium Confidence (review recommended)
- ...

### To remove: run `/genskills:dead-code --fix`
```

**Fix mode:**
- Remove orphan files
- Remove unused exports (keep the function if used internally)
- Remove unused dependencies: `npm uninstall <pkg>`
- Remove empty barrel files after cleanup
- Run linter and type-check after removal to verify nothing broke

### Step 6: Verify
- Run `npx tsc --noEmit` or equivalent type check
- Run test suite to confirm nothing broke
- If errors found, revert the problematic removal and report it

## Configuration
- `excludePaths`: string[] - paths to exclude from analysis
- `excludePatterns`: string[] - file patterns to skip (e.g., "*.stories.tsx")
- `minConfidence`: string - minimum confidence to report: "high" | "medium" | "low"
- `autoFix`: boolean - remove high-confidence dead code automatically (default: false)
