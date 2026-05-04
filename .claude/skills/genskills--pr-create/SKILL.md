---
name: genskills:pr-create
description: >
  Create pull requests with AI-generated titles, descriptions, and test plans.
  Triggers on: "create PR", "open PR", "pull request", "make PR", "submit PR".
user-invocable: true
argument-hint: "[base branch, defaults to main]"
allowed-tools: "Read, Grep, Glob, Bash(git *), Bash(gh *)"
genskills-version: "1.1.0"
genskills-category: "workflow"
genskills-depends:
  - genskills:git-commit
---

# PR Create

Create well-documented pull requests.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any PR conventions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Look for PR templates: `.github/pull_request_template.md` or `.github/PULL_REQUEST_TEMPLATE/`

### Step 1: Pre-flight Checks
- Run `git status` - warn if there are uncommitted changes
- Check if the current branch is `main`/`master` - refuse to create a PR from the default branch
- Determine the base branch (from `$ARGUMENTS` or default to main/master)
- Check if the branch tracks a remote and is up to date

### Step 2: Analyze Branch
- Run `git log <base>..HEAD --oneline` to see ALL commits on this branch
- Run `git diff <base>...HEAD` to see the full diff
- Read the changed files to understand the full scope of changes
- Count: files changed, insertions, deletions

### Step 3: Generate PR Content
If a PR template exists, fill it in. Otherwise use this format:

**Title**: Short (under 70 chars), descriptive, imperative mood - based on ALL commits, not just the latest

**Description** (use HEREDOC for proper formatting):
```markdown
## Summary
<1-3 bullet points describing what this PR does and why>

## Changes
<Grouped list of significant changes by area>

## Test Plan
<How to verify this PR works>
- [ ] Unit tests pass
- [ ] Manual testing steps specific to the changes

## Screenshots
<If UI changes, note that screenshots should be added>
```

### Step 4: Push and Create
- Push the branch if not already pushed: `git push -u origin <branch>`
- Create the PR using `gh pr create` with HEREDOC body format
- Add labels if the repo uses them: `gh pr edit --add-label "..."`
- If PR template was used, respect its required sections

### Step 5: Report
- Show the PR URL
- List suggested reviewers based on `git log` authorship of changed files
- Suggest: "Run `/genskills:code-review` to self-review before requesting reviews"

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `baseBranch`: string - default base branch (default: "main")
- `draft`: boolean - create as draft PR (default: false)
- `labels`: string[] - default labels to add
- `reviewers`: string[] - default reviewers to request
