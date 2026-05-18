---
name: genskills:task-tracker
description: >
  Track and manage project tasks, create TODO lists, and organize work items.
  Triggers on: "track tasks", "create task", "list tasks", "what's left to do",
  "project status", "task list".
user-invocable: true
argument-hint: "[action: list|add|done|status|clean] [task description or ID] [--priority high|medium|low] [--area frontend|backend|infra|docs]"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(git log*), Bash(git diff*), Bash(gh issue*), Bash(gh pr*)"
genskills-version: "1.3.0"
genskills-category: "project-management"
genskills-depends: []
---

# Task Tracker

Manage project tasks and track progress.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any task management conventions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Detect existing task tracking:
  - Files: `TODO.md`, `TASKS.md`, `ROADMAP.md`
  - GitHub Issues: `gh issue list --limit 1` to check if issues are used
  - Inline comments: `TODO`, `FIXME`, `HACK`, `XXX` in source
  - Project boards: `gh project list` if applicable

### Step 1: Parse Arguments
Parse `$ARGUMENTS`:
- `$0`: action - "list" | "add" | "done" | "status" | "clean" | "sync" (default: "list")
- `$1+`: task description, task ID, or search query
- `--priority`: "critical" | "high" | "medium" | "low" (default: "medium")
- `--area`: "frontend" | "backend" | "infra" | "docs" | "tests" | custom label
- `--assignee`: assign to GitHub user (for issue sync)
- `--issue`: create/link GitHub Issue

## Actions

### List (`list` or default)
Gather tasks from all sources and present unified view:

**Scan inline comments:**
```bash
# Search for TODO/FIXME/HACK/XXX comments (exclude build artifacts)
# Grep patterns: TODO, FIXME, HACK, XXX, @todo
```
- Exclude: `node_modules/`, `dist/`, `build/`, `vendor/`, `.git/`, `*.min.js`, lock files

**Scan task files:**
- Read `TODO.md`, `TASKS.md` if they exist
- Parse checkbox format: `- [ ] open task` / `- [x] completed task`

**Scan GitHub Issues:**
```bash
gh issue list --limit 50 --json number,title,labels,assignees,state,createdAt
```

**Classify and present:**

| Priority | Source | Description |
|---|---|---|
| Inline keywords | `FIXME` = high, `TODO` = medium, `HACK`/`XXX` = low |
| Task file | Parse `[critical]`, `[high]`, `[medium]`, `[low]` prefixes |
| GitHub Issues | Map labels: `bug` = high, `enhancement` = medium, `good first issue` = low |

**Group by:**
1. Priority (critical → low)
2. Area (frontend, backend, infra, docs, tests)
3. Source (inline, task file, GitHub Issues)

```
## Tasks Overview

### Critical (N)
- [FIXME] src/api/auth.ts:42 - Token refresh race condition
- [Issue #89] Production error on checkout flow

### High (N)
- [FIXME] src/db/queries.ts:156 - N+1 query in user listing
- [TODO] src/components/Modal.tsx:23 - Add keyboard trap for a11y

### Medium (N)
- [TODO] src/utils/format.ts:8 - Support i18n date formatting
- [Issue #92] Add dark mode toggle

### Low (N)
- [HACK] src/legacy/parser.ts:200 - Temp workaround, refactor after v2
- [XXX] src/config.ts:15 - Review defaults before release

### Summary
- Total open: N (inline: N, task file: N, issues: N)
- By area: frontend N, backend N, infra N, docs N, tests N
```

### Add (`add`)
Parse `$1+` as task description:

```
- [ ] [<priority>] [<area>] <description> (added: YYYY-MM-DD)
```

**Placement logic:**
1. If `--issue` flag: create GitHub Issue
   ```bash
   gh issue create --title "<description>" --label "<priority>,<area>"
   ```
2. If task file exists (`TODO.md`/`TASKS.md`): append to appropriate section
3. If neither: create `TODO.md` at project root with initial structure:
   ```markdown
   # Project Tasks

   ## Critical

   ## High

   ## Medium
   - [ ] [medium] <description> (added: YYYY-MM-DD)

   ## Low

   ## Completed
   ```

**Confirm after adding:**
```
✓ Task added: "<description>" [<priority>] [<area>]
  Location: TODO.md line N (or Issue #N)
```

### Done (`done`)
Parse `$1` as task identifier:
- Line number in task file
- Task description fragment (fuzzy match)
- GitHub Issue number (`#123`)
- Inline comment location (`src/file.ts:42`)

**Mark complete:**
- Task file: `- [ ]` → `- [x]` and add `(completed: YYYY-MM-DD)`
- Move to `## Completed` section if one exists
- GitHub Issue: `gh issue close <number> --reason completed`
- Inline comment: remove the TODO/FIXME comment (confirm with user first)

```
✓ Completed: "<description>"
  Was: TODO.md line 15 (or Issue #123 closed)
```

### Status (`status`)
Show comprehensive project status:

```
## Project Status

### Task Summary
| Source | Open | Completed | Total |
|---|---|---|---|
| Task file | N | N | N |
| Inline TODOs | N | - | N |
| GitHub Issues | N | N | N |
| **Total** | **N** | **N** | **N** |

### By Priority
| Priority | Count | Oldest |
|---|---|---|
| Critical | N | YYYY-MM-DD |
| High | N | YYYY-MM-DD |
| Medium | N | YYYY-MM-DD |
| Low | N | YYYY-MM-DD |

### By Area
| Area | Open Tasks |
|---|---|
| Frontend | N |
| Backend | N |
| Infrastructure | N |
| Documentation | N |
| Tests | N |

### Stale Tasks (>30 days old)
- [TODO] src/old-file.ts:15 - added 45 days ago
- [Issue #45] - created 60 days ago, no activity

### Recent Activity
- Last 5 commits: `git log --oneline -5`
- Recently closed: `gh issue list --state closed --limit 5`

### Velocity (last 30 days)
- Tasks completed: N
- Issues closed: N
- Commits: N
```

### Clean (`clean`)
Remove stale or resolved tasks:
- Find inline TODOs in code that has been significantly refactored (function removed, file rewritten)
- Find task file entries that reference deleted files or resolved issues
- Find duplicate tasks (same description in multiple places)
- Find completed tasks older than N days that can be archived

**Confirm before removing:**
```
Found N stale/resolved tasks:
1. [TODO] src/deleted-file.ts:10 - file no longer exists
2. [FIXME] src/api.ts:42 - code was refactored, issue resolved
3. [Issue #45] - closed 90 days ago, still in TODO.md

Remove these? (y/n/select)
```

### Sync (`sync`)
Synchronize between task sources:
- Create GitHub Issues from high-priority inline TODOs
- Update task file from closed GitHub Issues
- Flag inconsistencies (task marked done in file but issue still open)

```bash
# Find TODOs that should be issues
# Find issues that are done but still in task file
# Report discrepancies
```

## Report Template
```
## Task Tracker Report

### Action: <action performed>
### Result: <summary>

### Changes Made
- <list of changes>

### Current State
- Open tasks: N
- Completed today: N

### Suggestions
- N critical tasks need attention
- N stale tasks could be cleaned up
- Run `/genskills:task-tracker clean` to remove resolved items
```

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `taskFile`: string - path to task file (default: "TODO.md")
- `useGitHubIssues`: boolean - integrate with GitHub Issues (default: auto-detect)
- `ignorePaths`: string[] - paths to skip when scanning for TODOs
- `staleThreshold`: number - days before a task is considered stale (default: 30)
- `archiveCompleted`: boolean - move completed tasks to archive section (default: true)
- `defaultPriority`: "critical" | "high" | "medium" | "low" - default for new tasks (default: "medium")
- `autoSync`: boolean - sync task file with GitHub Issues on list/status (default: false)
