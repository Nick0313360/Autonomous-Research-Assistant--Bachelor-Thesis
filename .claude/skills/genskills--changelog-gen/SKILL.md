---
name: genskills:changelog-gen
description: >
  Generate and maintain a CHANGELOG.md from git history, following Keep a Changelog format.
  Triggers on: "generate changelog", "update changelog", "what changed", "changelog".
user-invocable: true
argument-hint: "[version or 'unreleased'] [--since <tag|date>] [--format keep-a-changelog|conventional]"
allowed-tools: "Read, Write, Edit, Bash(git log*), Bash(git tag*), Bash(git diff*), Bash(gh pr*), Bash(gh issue*)"
genskills-version: "1.3.0"
genskills-category: "project-management"
genskills-depends:
  - genskills:git-commit
---

# Changelog Generator

Generate and maintain a changelog from git history.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any changelog conventions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Check for existing `CHANGELOG.md` to preserve its format, style, and link conventions

### Step 1: Parse Arguments
Parse `$ARGUMENTS`:
- First positional: version number (e.g., `1.2.0`) or `unreleased`
- `--since`: starting point - tag name, commit SHA, or date (default: last tag)
- `--format`: output format - "keep-a-changelog" | "conventional" (default: "keep-a-changelog")
- `--include-internal`: include chore/ci/build commits (default: false)
- `--dry-run`: show what would be generated without writing

If no version specified, update the `[Unreleased]` section.

### Step 2: Analyze Git History
Gather changes from multiple sources for accuracy:

```bash
# Find the range
git describe --tags --abbrev=0                           # Last tag
git log <last-tag>..HEAD --oneline --no-merges           # Commits since
git log <last-tag>..HEAD --merges --oneline              # Merge commits (for PR info)

# Enrich with PR data
gh pr list --state merged --base main --limit 100 --json number,title,labels,body

# Get contributor info
git shortlog -sn --no-merges <last-tag>..HEAD
```

**Parse each commit:**
- Extract conventional commit type and scope: `feat(auth): add SSO support`
- Extract PR number from message: `(#123)` or merge commit
- Extract breaking change markers: `BREAKING CHANGE:` footer or `!` after type
- Extract issue references: `Fixes #456`, `Closes #789`
- Detect squash-merged PRs and use PR title over individual commits

### Step 3: Categorize Changes
Group commits into categories based on format:

**Keep a Changelog format:**

| Category | Commit Types | Meaning |
|---|---|---|
| **Added** | `feat:`, `feature:` | New features and capabilities |
| **Changed** | `refactor:`, `perf:`, non-breaking changes | Changes to existing functionality |
| **Deprecated** | `deprecate:`, marked as deprecated | Features to be removed in future |
| **Removed** | `remove:`, deleted features | Removed features |
| **Fixed** | `fix:`, `bugfix:` | Bug fixes |
| **Security** | `security:`, vulnerability fixes | Security-related changes |

**Conventional Changelog format:**

| Category | Commit Types |
|---|---|
| **Features** | `feat:` |
| **Bug Fixes** | `fix:` |
| **Performance** | `perf:` |
| **Breaking Changes** | `BREAKING CHANGE:` or `!` |
| **Documentation** | `docs:` (if included) |

**Rules:**
- Skip internal commits by default: `chore:`, `ci:`, `build:`, `style:`, `test:`
- Write entries from the **user's perspective** (what changed for them), not developer's
- Include PR/issue references where available: `([#123](url))`
- Deduplicate - if multiple commits relate to the same feature, combine into one entry
- Group related changes under a descriptive sub-heading when there are 5+ entries in a category
- Preserve existing entry formatting when updating an existing changelog
- For monorepos, optionally group by package/workspace

### Step 4: Generate/Update CHANGELOG.md

**If CHANGELOG.md exists:**
- Parse existing content to understand structure and link format
- Insert new section at the correct position (below header, above previous version)
- Update `[Unreleased]` comparison link if using link references
- Preserve all existing entries untouched

**If CHANGELOG.md doesn't exist, create:**
```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Feature description ([#PR](url))

### Fixed
- Bug fix description ([#PR](url))

## [1.0.0] - YYYY-MM-DD

### Added
- Initial release features

[Unreleased]: https://github.com/owner/repo/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/owner/repo/releases/tag/v1.0.0
```

**Link references:**
- Auto-detect GitHub repo URL from `git remote get-url origin`
- Generate comparison links between versions
- Link PR numbers to GitHub PR pages
- Link issue numbers to GitHub issue pages

### Step 5: Validate
- Verify markdown formatting is correct
- Ensure no duplicate entries
- Verify version ordering (newest first)
- Check that link references resolve correctly
- Verify date format consistency (YYYY-MM-DD)

### Step 6: Report
```
## Changelog Update

### Version: <version or Unreleased>
### Period: <from-tag> → HEAD (<N> commits, <N> PRs)

### Entries Generated
| Category | Count |
|---|---|
| Added | N |
| Changed | N |
| Fixed | N |
| Security | N |
| Total | N |

### Skipped (internal)
- N chore/ci/build/test commits excluded

### Contributors
- @user1 (N commits)
- @user2 (N commits)

### Next Steps
- Review the changelog entries for accuracy
- Run `/genskills:git-commit` to commit the changelog update
- Run `/genskills:release-notes` to generate user-facing release notes
```

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `format`: "keep-a-changelog" | "conventional" - changelog format (default: "keep-a-changelog")
- `includeInternal`: boolean - include chore/ci/build commits (default: false)
- `linkPRs`: boolean - link PR numbers to GitHub (default: true)
- `linkIssues`: boolean - link issue references to GitHub (default: true)
- `skipTypes`: string[] - commit types to always skip
- `groupByScope`: boolean - sub-group entries by scope in monorepos (default: false)
- `contributors`: boolean - include contributor list (default: true)
