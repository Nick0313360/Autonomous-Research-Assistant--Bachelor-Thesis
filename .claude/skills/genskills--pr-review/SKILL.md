---
name: genskills:pr-review
description: >
  Review incoming pull requests - fetch diff, analyze changes, post review comments.
  Triggers on: "review PR", "review pull request", "PR review", "check this PR",
  "review #123".
user-invocable: true
argument-hint: "[PR number or URL] - e.g., '#123' or 'https://github.com/org/repo/pull/123'"
allowed-tools: "Read, Grep, Glob, WebFetch, Bash(gh *), Bash(git *), Bash(npm test*), Bash(npx *)"
genskills-version: "1.2.0"
genskills-category: "workflow"
genskills-depends: []
---

# PR Review

Perform thorough pull request reviews with actionable feedback.

## Process

### Step 0: Load Context
- Check `CLAUDE.md` for review guidelines, team conventions, and quality standards
- Check `${CLAUDE_SKILL_DIR}/_config.json` for preferences

### Step 1: Fetch PR Information
Parse `$ARGUMENTS` for PR number or URL.

```bash
gh pr view <number> --json title,body,author,baseRefName,headRefName,files,additions,deletions,commits
gh pr diff <number>
gh pr checks <number>
```

Gather:
- PR title, description, and linked issues
- Full diff
- CI status
- File list and change statistics
- Commit history on the branch

### Step 2: Analyze Changes

Review each changed file across these dimensions:

**Correctness:**
- Logic errors, off-by-one, null/undefined handling
- Race conditions in async code
- Missing error handling for new code paths
- Edge cases not covered

**Security:**
- SQL injection, XSS, command injection risks
- Hardcoded secrets or credentials
- Auth/authz bypasses
- Unsafe deserialization or eval usage

**Performance:**
- N+1 queries
- Unnecessary re-renders (React)
- Missing indexes for new queries
- Large payload or unbounded data fetching
- Memory leaks (event listeners, subscriptions)

**Maintainability:**
- Clear naming and intent
- Appropriate abstraction level (not over/under-engineered)
- Consistent with existing codebase patterns
- DRY without premature abstraction

**Testing:**
- Are new code paths tested?
- Are edge cases covered?
- Are tests testing behavior, not implementation?
- Snapshot tests updated if UI changed?

**Types:**
- Proper TypeScript types (no unnecessary `any`)
- API contract changes reflected in types
- Null/undefined handled in types

### Step 3: Check Context
- Read surrounding code for files with significant changes (not just the diff)
- Check if related code elsewhere needs updating
- Verify imports are used
- Check for breaking changes to public APIs

### Step 4: Classify Findings

| Level | Meaning | Prefix |
|---|---|---|
| **Blocker** | Must fix before merge - bug, security issue, data loss | 🔴 |
| **Suggestion** | Should fix - performance, maintainability | 🟡 |
| **Nit** | Optional - style, minor improvement | 🔵 |
| **Question** | Need clarification from author | ❓ |
| **Praise** | Good pattern or clever solution worth calling out | 👍 |

### Step 5: Generate Review

```markdown
## PR Review: #<number> - <title>

### Summary
<1-2 sentence overall assessment>

### Verdict: ✅ Approve / ⚠️ Request Changes / 💬 Comment

### Blockers (must fix)
- 🔴 **file.ts:42** - <issue description and suggested fix>

### Suggestions (should fix)
- 🟡 **file.ts:88** - <suggestion>

### Nits (optional)
- 🔵 **file.ts:15** - <nit>

### Questions
- ❓ **file.ts:60** - <question about intent>

### What I Liked
- 👍 Clean separation of concerns in the new service layer
- 👍 Good test coverage for edge cases

### Testing Checklist
- [ ] Unit tests cover new logic
- [ ] Edge cases handled
- [ ] Integration test for API changes
- [ ] Manual testing steps documented
```

### Step 6: Post Review (if requested)
Ask user before posting:
```
Post this review to GitHub? (approve/request-changes/comment)
```

If confirmed:
```bash
gh pr review <number> --approve --body "..."
# or
gh pr review <number> --request-changes --body "..."
# or
gh pr review <number> --comment --body "..."
```

## Configuration
- `autoPost`: boolean - post review to GitHub without asking (default: false)
- `focusAreas`: string[] - prioritize certain review aspects
- `skipNits`: boolean - omit nit-level findings (default: false)
- `maxFileSize`: number - skip files larger than N lines in review (default: 1000)
