---
name: genskills:code-review
description: >
  Perform comprehensive code reviews with security, performance, and best-practice analysis.
  Triggers on: "review this code", "code review", "check my code", "review PR", "review changes".
user-invocable: true
argument-hint: "[file or directory] [--mode quick|deep|security] [--pr <number>]"
allowed-tools: "Read, Edit, Grep, Glob, WebFetch, Bash(git diff*), Bash(git log*), Bash(git blame*), Bash(npm test*), Bash(npm run*), Bash(npx vitest*), Bash(npx jest*), Bash(gh pr*)"
genskills-version: "1.3.0"
genskills-category: "code-quality"
genskills-depends: []
---

# Code Review

Perform a thorough, multi-dimensional code review.

## Review Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - it contains project conventions, patterns, and rules you MUST follow
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Identify the tech stack from `package.json`, `pyproject.toml`, `Cargo.toml`, or equivalent

### Step 1: Parse Arguments & Gather Context
Parse `$ARGUMENTS`:
- First positional: file or directory to review
- `--mode`: "quick" (surface-level) | "deep" (thorough, read full files) | "security" (security-focused)
- `--pr <number>`: review a specific PR via `gh pr diff <number>`
- `--staged`: review only staged changes
- `--since <ref>`: review changes since a git ref (commit, tag, branch)

**Gathering changes:**
- If `--pr` specified: `gh pr diff <number>` and `gh pr view <number> --json title,body,files`
- If file/directory specified: focus review on that path
- If `--staged`: `git diff --cached`
- If nothing specified: `git diff HEAD~1` (latest commit changes)

**Always also:**
- Read the full files being reviewed (not just the diff) to understand surrounding context
- Run `git log --oneline -5 -- <file>` to understand recent change history
- Use `git blame` on critical sections to understand authorship and change reasoning

### Step 2: Analyze Code Quality
Check for issues across these dimensions:

**Correctness:**
- Logic errors, edge cases, off-by-one errors
- Null/undefined handling, optional chaining misuse
- Race conditions in async code, promise handling
- Missing return statements, unreachable code
- Incorrect regex patterns, string handling edge cases

**Security:**
- Injection vulnerabilities: SQL, XSS, command injection, template injection
- Auth/authz issues: missing checks, IDOR, privilege escalation
- Data exposure: PII logging, verbose error messages, leaked secrets
- Hardcoded secrets, API keys, tokens (regex: `(?i)(api[_-]?key|secret|password|token)\s*[=:]\s*['"][^'"]+`)
- Unsafe deserialization, eval usage, prototype pollution

**Performance:**
- N+1 queries, missing database indexes
- Unnecessary iterations, O(n²) when O(n) is possible
- Memory leaks: unclosed connections, event listener accumulation, subscription cleanup
- Missing request/response caching, unnecessary re-renders (React)
- Unintended synchronous blocking, unbounded data fetching
- Large payloads without pagination or streaming

**Maintainability:**
- Code complexity: cyclomatic complexity, deep nesting (>3 levels)
- Naming clarity: variable/function names that don't convey intent
- DRY violations: repeated patterns (3+ occurrences)
- Function length: >50 lines is a warning, >100 is critical
- Over-engineering: unnecessary abstractions, premature generalization
- Under-documentation: complex business logic without comments

**Error Handling:**
- Missing try/catch on async operations
- Unhandled promise rejections, missing `.catch()`
- Error propagation: swallowed errors, empty catch blocks
- Missing error boundaries (React), error pages (Next.js/Remix)
- Generic error messages that hide root cause

**Type Safety:**
- Type mismatches, unsafe `as` casts, `any` usage
- Missing null checks, non-null assertions (`!`) without validation
- API contract: request/response types matching actual data
- Generic type constraints too loose or missing

**Concurrency:**
- Race conditions in shared state access
- Missing locks, atomic operations, or optimistic concurrency
- Deadlock potential in multi-resource locking
- Stale closure bugs in React useEffect/useCallback

**API & Contracts:**
- Breaking changes to public APIs without version bump
- Missing backward compatibility for consumers
- Request/response validation (zod, joi, class-validator)
- Missing or incorrect HTTP status codes
- Missing rate limiting on public endpoints

### Step 3: Check Project Patterns
- Read nearby files to understand existing patterns and conventions
- Cross-reference with `CLAUDE.md` rules if present
- Flag deviations from established patterns (naming, imports, file structure, error handling style)
- Check for consistent import ordering, barrel exports, naming conventions
- Verify new dependencies are justified and align with project choices

### Step 4: Verify Test Coverage
- Check if changed code has corresponding tests
- Run relevant test suites to verify they pass: `npm test`, `npx vitest run`, or `npx jest`
- Flag changed logic that lacks test coverage
- Check for missing edge-case tests on new logic
- Verify that new error paths have test coverage

### Step 5: Classify Findings

| Level | Meaning | Action Required |
|---|---|---|
| **Critical** | Bug, security vulnerability, data loss risk | Must fix before merge |
| **Warning** | Performance issue, poor error handling, maintainability concern | Should fix |
| **Suggestion** | Code quality improvement, better pattern available | Nice to have |
| **Praise** | Well-written code, good patterns, clever solutions | Positive reinforcement |

### Step 6: Generate Report
```
## Code Review Summary

### Critical Issues (must fix)
- [file:line] Description of issue + suggested fix + why it matters

### Warnings (should fix)
- [file:line] Description + recommendation

### Suggestions (nice to have)
- [file:line] Improvement opportunity

### Positive Highlights
- What was done well - good patterns, clean abstractions, thorough tests

### Test Coverage
- Coverage status for changed code
- Missing test scenarios with specific suggestions

### Overall Assessment
Verdict: ✅ Approve / ⚠️ Request Changes / 💬 Needs Discussion
Brief summary with confidence level and key risk areas.
```

### Step 7: Offer Follow-up Actions
After the report, suggest relevant next steps:
- "Run `/genskills:test-generator` to add missing tests for uncovered code"
- "Run `/genskills:security-audit` for a deeper security analysis" (if security issues found)
- "Run `/genskills:refactor` on [file] to address complexity warnings"
- "Run `/genskills:type-check` to validate type safety" (if type issues found)

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `defaultMode`: "quick" | "deep" | "security-focused" - review depth
- `languages`: string[] - focus languages
- `ignorePaths`: string[] - paths to skip
- `autoFix`: boolean - if true, apply simple fixes directly with Edit tool
- `maxFileLines`: number - skip files larger than N lines (default: 1000)
- `focusAreas`: string[] - prioritize specific review dimensions
