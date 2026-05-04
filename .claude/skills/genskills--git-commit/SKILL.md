---
name: genskills:git-commit
description: >
  Create well-structured git commits with conventional commit format,
  smart staging, and AI-generated messages. Triggers on: "commit",
  "save changes", "git commit", "stage and commit".
user-invocable: true
argument-hint: "[optional commit message]"
allowed-tools: "Read, Grep, Glob, Bash(git *)"
genskills-version: "1.1.0"
genskills-category: "workflow"
genskills-depends: []
---

# Git Commit

Create structured, well-described git commits.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any commit conventions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Check `git log --oneline -5` to understand the repo's existing commit message style

### Step 1: Analyze Changes
- Run `git status` to see all changed and untracked files (never use `-uall` flag)
- Run `git diff` (unstaged) and `git diff --cached` (staged)
- If nothing is staged AND nothing is changed, inform the user there's nothing to commit
- Read the changed files to understand what the changes actually do

### Step 2: Smart Staging
If no files are staged:
- Group related changes logically
- If changes span multiple concerns, suggest splitting into separate commits
- Stage the appropriate files using `git add <specific files>`
- **Never** use `git add -A` or `git add .` - always be explicit about files
- **Never** stage files that look like secrets (`.env`, credentials, keys)
- Warn the user if untracked files look like they should be gitignored

### Step 3: Generate Commit Message
If `$ARGUMENTS` is provided, use it as the commit message (but still follow format).
Otherwise, generate one:

**Conventional Commit Format:**
```
<type>(<scope>): <description>

<body>

<footer>
```

**Types**: feat, fix, docs, style, refactor, perf, test, build, ci, chore
**Scope**: The module/component affected (optional but preferred)
**Description**: Imperative mood, no period, max 72 chars, lowercase start
**Body**: What changed and **why** (not how) - wrap at 72 chars
**Footer**: Breaking changes (`BREAKING CHANGE:`), issue references (`Fixes #123`)

**Rules**:
- Match the repository's existing commit style (conventional, angular, etc.)
- If the repo doesn't use conventional commits, use a clear descriptive message instead
- Never write generic messages like "update code" or "fix bug"
- Use HEREDOC format for the commit message to preserve formatting

### Step 4: Commit
- Create the commit with the generated message using HEREDOC format
- Show the commit hash and summary
- **Never** use `--no-verify` - if hooks fail, diagnose and fix the issue
- **Never** amend the previous commit unless explicitly asked
- If pre-commit hooks fail, fix the issues, re-stage, and create a NEW commit

### Step 5: Post-commit
- Show `git log --oneline -5` for context
- Suggest relevant next steps:
  - "Run `git push` to push to remote"
  - "Run `/genskills:pr-create` to open a pull request"
  - Continue working if more changes are pending

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `commitFormat`: "conventional" | "angular" | "freeform" - commit message format
- `defaultType`: string - default commit type if not obvious (e.g., "feat")
- `includeScope`: boolean - whether to include scope in message (default: true)
- `signoff`: boolean - add Signed-off-by line (default: false)
