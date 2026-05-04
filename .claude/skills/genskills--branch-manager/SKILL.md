---
name: genskills:branch-manager
description: >
  Manage git branches - create, switch, merge, rebase, clean up stale branches.
  Triggers on: "manage branches", "clean branches", "create branch",
  "merge branch", "rebase", "branch cleanup".
user-invocable: true
argument-hint: "[action: create|cleanup|merge|rebase|status] [branch name]"
allowed-tools: "Bash(git *), Bash(gh *), Read, Grep, Glob"
genskills-version: "1.1.0"
genskills-category: "workflow"
genskills-depends: []
---

# Branch Manager

Manage git branches efficiently.

## Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any branching conventions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Detect the default branch: `git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@'` or fall back to main/master

## Actions

### Create (`$0` = "create")
- Create a new branch from the current or specified base
- Use naming convention: `<type>/<short-description>` (kebab-case)
- Types: `feature/`, `fix/`, `chore/`, `docs/`, `refactor/`, `hotfix/`
- Example: `feature/add-user-auth`
- Switch to the new branch
- Suggest: `git push -u origin <branch>` to set up tracking

### Cleanup (`$0` = "cleanup")
- Fetch latest remote state: `git fetch --prune`
- List all local branches with last commit date
- Identify merged branches: `git branch --merged <default-branch>`
- Identify stale branches (no commits in 30+ days)
- Check for open PRs before suggesting deletion: `gh pr list --head <branch>`
- **Never delete branches with open PRs** - warn the user
- **Never force delete** (`-D`) without explicit confirmation - use safe delete (`-d`) first
- Show a summary of what will be deleted and **ask for confirmation**
- Clean up remote tracking: `git remote prune origin`

### Merge (`$0` = "merge")
- Merge `$1` into the current branch
- Before merging, check if the branch is up to date with remote
- If conflicts arise, list the conflicting files and help resolve each one
- **Never** use `--force` or destructive operations without explicit confirmation
- After merge, suggest running tests to verify

### Rebase (`$0` = "rebase")
- **WARNING**: Check if the branch has been pushed and has open PRs - rebase rewrites history
- If the branch is shared (has remote tracking AND open PRs), **warn the user** about force-push implications and ask for confirmation
- Rebase current branch onto `$1` (defaults to default branch)
- If conflicts arise, help resolve them step by step
- **Never** use `--force-with-lease` or `--force` push without explicit user confirmation
- Do NOT use `-i` (interactive) flag - it requires terminal input

### Status (default if no action specified)
- Show current branch and its tracking status
- Show `git log --oneline -10`
- Show all branches with last commit date: `git branch -v`
- Show uncommitted changes: `git status --short`
- Show ahead/behind status vs remote

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `defaultBranch`: string - default base branch (default: auto-detect)
- `branchPrefix`: string - custom prefix instead of type/ (e.g., "username/")
- `staleDays`: number - days before a branch is considered stale (default: 30)
