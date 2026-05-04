---
name: genskills:doc-gen
description: >
  Generate documentation for code - inline comments, JSDoc/docstrings, module docs.
  Triggers on: "document this", "add docs", "generate documentation",
  "add comments", "write docstrings".
user-invocable: true
argument-hint: "[file or directory] [--style jsdoc|tsdoc|google|numpy|sphinx] [--scope public|all] [--update]"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(git diff*)"
genskills-version: "1.3.0"
genskills-category: "documentation"
genskills-depends: []
---

# Documentation Generator

Generate inline documentation for code.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any documentation style/conventions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Find existing documented functions in the project to match the established style exactly
- Check for doc generation tooling: `typedoc`, `jsdoc`, `sphinx`, `godoc`, `rustdoc`, `dokka`

### Step 1: Parse Arguments
Parse `$ARGUMENTS`:
- First positional: file or directory to document
- `--style`: override doc style - "jsdoc" | "tsdoc" | "google" | "numpy" | "sphinx" | "godoc" | "rustdoc"
- `--scope`: what to document - "public" (exports only, default) | "all" (include private)
- `--update`: update existing docs (add missing params, fix outdated descriptions)
- `--changed`: only document recently changed code (`git diff --name-only HEAD~1`)
- `--module`: also generate module-level documentation headers

If no arguments, ask the user what to document.

### Step 2: Detect Language & Convention
Auto-detect from file extension and existing docs:

| Language | Doc Format | Convention |
|---|---|---|
| TypeScript/JavaScript | JSDoc (`/** */`) | Check if project uses TSDoc variant (`@remarks`, `@typeParam`) |
| Python | Docstrings (`"""..."""`) | Detect: Google, NumPy, or Sphinx (reST) from existing docs |
| Go | GoDoc (`//` above declarations) | Single-line or multi-line comment blocks |
| Rust | `///` doc comments | Markdown with `# Examples`, `# Panics`, `# Errors` sections |
| Java/Kotlin | Javadoc/KDoc (`/** */`) | `@param`, `@return`, `@throws` |
| C# | XML doc (`/// <summary>`) | `<param>`, `<returns>`, `<exception>` |
| PHP | PHPDoc (`/** */`) | `@param`, `@return`, `@throws` |
| Ruby | YARD (`# @param`) | `@param`, `@return`, `@raise` |
| Swift | `///` or `/** */` | Markdown with `- Parameters:`, `- Returns:`, `- Throws:` |

**Match existing style exactly** - if the project uses Google-style Python docstrings, don't switch to NumPy.

### Step 3: Identify What Needs Documentation
Scan target files and classify documentation needs:

| Priority | What | When to Document |
|---|---|---|
| **1 - Critical** | Exported/public functions and classes | Always - this is the API surface |
| **2 - High** | Type definitions, interfaces, enums | Always - explain shape and purpose |
| **3 - Medium** | Complex private functions | When logic isn't self-evident (>20 lines, complex branching) |
| **4 - Medium** | Module-level headers | When `--module` flag or no existing header |
| **5 - Low** | Configuration constants, magic numbers | When meaning isn't obvious from name |

**Skip (do NOT document):**
- Simple getters/setters with obvious purpose (`getName()` → `string`)
- Functions whose name + signature already explain everything (`function add(a: number, b: number): number`)
- One-line utility functions with clear names
- Test files (unless explicitly requested)
- Generated code (`.generated.ts`, `*.g.cs`)
- Already well-documented functions (unless `--update` flag)

### Step 4: Generate Documentation
For each function/class/type, generate appropriate documentation:

**Function documentation includes:**
- **Description**: What it does and **why** (not how it's implemented)
- **Parameters**: name, type, description, default values, constraints, valid ranges
- **Returns**: type and description of what's returned, including edge cases
- **Throws/Raises**: specific error types and conditions that trigger them
- **Examples**: usage examples for complex or non-obvious APIs (when `--examples` or complex API)
- **Deprecation**: `@deprecated` with migration path if applicable
- **See also**: related functions or documentation links

**Class documentation includes:**
- Purpose and responsibility of the class
- Usage pattern (singleton, factory, instantiate directly)
- Key methods overview
- Generic type parameter descriptions

**Interface/Type documentation includes:**
- What the shape represents in the domain
- When to use this type vs. alternatives
- Required vs. optional field explanations

**Module documentation includes:**
- What the module does and its role in the system
- Key exports and their relationships
- Usage pattern from consumer's perspective

**JSDoc example:**
```typescript
/**
 * Resolves a user's permissions based on their role and team membership.
 *
 * Combines role-based permissions with team-level overrides, applying
 * the most permissive grant. Results are cached for the session duration.
 *
 * @param userId - The user's unique identifier
 * @param options - Resolution options
 * @param options.includeInherited - Include permissions inherited from parent teams (default: true)
 * @param options.scope - Limit to a specific resource scope
 * @returns Resolved permission set with grant sources for audit
 * @throws {UserNotFoundError} If the user ID doesn't exist
 * @throws {PermissionServiceError} If the permission backend is unavailable
 *
 * @example
 * const perms = await resolvePermissions('usr_123', { scope: 'billing' });
 * if (perms.has('billing:write')) { ... }
 *
 * @see {@link RoleService} for role management
 */
```

**Python docstring example (Google style):**
```python
def resolve_permissions(user_id: str, include_inherited: bool = True) -> PermissionSet:
    """Resolve a user's permissions based on role and team membership.

    Combines role-based permissions with team-level overrides, applying
    the most permissive grant. Results are cached for the session duration.

    Args:
        user_id: The user's unique identifier.
        include_inherited: Include permissions inherited from parent teams.
            Defaults to True.

    Returns:
        Resolved permission set with grant sources for audit.

    Raises:
        UserNotFoundError: If the user ID doesn't exist.
        PermissionServiceError: If the permission backend is unavailable.

    Example:
        >>> perms = resolve_permissions("usr_123")
        >>> perms.has("billing:write")
        True
    """
```

**Writing rules:**
- Write documentation that **adds value** beyond what the code already says
- Don't restate the function name: `/** Gets the user */` on `getUser()` is worthless
- Be specific about edge cases: what happens with null input, empty arrays, boundary values
- Document **why** the function exists, not just what it does (when the "why" isn't obvious)
- Match the existing documentation voice, tense, and level of detail
- Preserve all existing documentation - only add where missing or enhance where outdated
- For `--update` mode: fix outdated param names, add missing params, update return types

### Step 5: Apply Documentation
- Add documentation comments using the Edit tool
- Only modify documentation, **never change the code itself**
- For module-level docs, add at the top of the file (after imports/license headers)
- Preserve formatting: respect line width conventions (80/100/120 chars)
- Respect import ordering - don't add docs between import groups

### Step 6: Report
```
## Documentation Report

### Files Documented
| File | Functions | Types | Module Header |
|---|---|---|---|
| src/services/auth.ts | 5 added | 2 added | ✓ |
| src/utils/format.ts | 3 added | 1 added | - |

### Summary
| Metric | Count |
|---|---|
| Functions documented | N |
| Types documented | N |
| Module headers added | N |
| Files modified | N |
| Skipped (already documented) | N |
| Skipped (trivial) | N |

### Documentation Style
- Format: JSDoc / TSDoc / Google docstring / ...
- Matched from: existing project conventions

### Coverage After
- Public API: N/N documented (N%)
- Complex private functions: N/N documented (N%)

### Follow-up
- Run `/genskills:api-docs` to generate API reference documentation
- Run `/genskills:readme-gen` to update project README
- Run typedoc/jsdoc/sphinx to generate static documentation site
```

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `style`: "jsdoc" | "tsdoc" | "google" | "numpy" | "sphinx" - override doc style
- `includeExamples`: boolean - always include @example blocks (default: false, only for complex APIs)
- `includePrivate`: boolean - document private functions too (default: false)
- `includeModule`: boolean - add module-level headers (default: false)
- `lineWidth`: number - max line width for doc comments (default: from editorconfig or 100)
- `updateExisting`: boolean - update outdated existing docs (default: false)
