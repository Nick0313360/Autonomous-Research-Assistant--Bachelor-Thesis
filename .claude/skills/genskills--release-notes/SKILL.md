---
name: genskills:release-notes
description: >
  Generate polished release notes for a version, suitable for GitHub Releases
  or user-facing announcements. Triggers on: "release notes", "write release",
  "create release", "publish release".
user-invocable: true
argument-hint: "[version tag] [--publish] [--prerelease] [--target github|slack|email]"
allowed-tools: "Read, Write, Grep, Glob, Bash(git log*), Bash(git tag*), Bash(git shortlog*), Bash(git diff*), Bash(gh release*), Bash(gh pr*)"
genskills-version: "1.3.0"
genskills-category: "project-management"
genskills-depends:
  - genskills:changelog-gen
---

# Release Notes

Generate polished release notes for public consumption.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any release conventions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Check for existing releases to match tone and format: `gh release list --limit 5`
- If previous releases exist, read the most recent one to match style: `gh release view <tag>`

### Step 1: Parse Arguments & Determine Version
Parse `$ARGUMENTS`:
- First positional: version tag (e.g., `v1.2.0`)
- `--publish`: create the GitHub Release after generating notes
- `--prerelease`: mark as pre-release
- `--draft`: create as draft release
- `--target`: output format - "github" (default) | "slack" | "email" | "markdown"
- `--attach`: attach build artifacts from dist/ or build/

If no version provided, analyze changes and suggest based on semver:

| Commit Pattern | Suggested Bump |
|---|---|
| `BREAKING CHANGE:` footer or `!` in type | **major** |
| `feat:` commits present | **minor** |
| Only `fix:` commits | **patch** |

Show current version (from package.json, pyproject.toml, Cargo.toml, or latest tag) and suggested next.

### Step 2: Gather Changes
Collect information from multiple sources:

```bash
# Tag range
git describe --tags --abbrev=0                                    # Previous tag
git log <prev-tag>..HEAD --oneline --no-merges                   # Commits

# PR details (richer descriptions than commits)
gh pr list --state merged --base main --limit 100 --json number,title,body,labels,author

# Contributors
git shortlog -sn --no-merges <prev-tag>..HEAD

# Stats
git diff --stat <prev-tag>..HEAD | tail -1                       # Files changed, insertions, deletions
```

**Source priority:**
1. `CHANGELOG.md` entries for this version (if already updated - best source)
2. PR titles and descriptions (user-facing language, linked issues)
3. Commit messages (fallback for changes without PRs)

### Step 3: Write Release Notes
Create user-friendly release notes - write for **end users**, not developers.

**GitHub format (default):**
```markdown
# v1.2.0

## Highlights
<1-3 sentences summarizing the most impactful changes - what users will notice first>

## What's New
- **Feature Name**: Brief user-facing description ([#PR](url))
- **Feature Name**: Brief user-facing description ([#PR](url))

## Improvements
- Performance: description of improvement ([#PR](url))
- UX: description of enhancement ([#PR](url))

## Bug Fixes
- Fixed issue where X happened when Y ([#PR](url))
- Fixed crash on Z under certain conditions ([#PR](url))

## Breaking Changes
> ⚠️ This release contains breaking changes.

- **What changed**: Description of the breaking change
- **Migration**: Step-by-step migration instructions
  ```diff
  - oldFunction(arg1, arg2)
  + newFunction({ arg1, arg2, newArg })
  ```

## Security
- Fixed [CVE-XXXX-XXXXX]: description ([#PR](url))

## Dependencies
- Updated package-name from v1.0 to v2.0

## Stats
- **N** commits from **N** contributors
- **N** files changed, **N** insertions, **N** deletions

## Contributors
Thanks to the following contributors for this release:
@user1, @user2, @user3

**Full Changelog**: [`v1.1.0...v1.2.0`](https://github.com/owner/repo/compare/v1.1.0...v1.2.0)
```

**Slack format (`--target slack`):**
```
🚀 *v1.2.0 Released*

*Highlights:* <summary>

*What's New:*
• Feature Name - description
• Feature Name - description

*Bug Fixes:*
• Fixed X when Y

<full release notes link>
```

**Email format (`--target email`):**
```
Subject: [Project] v1.2.0 Released - <highlight summary>

Hi team,

We've released v1.2.0 with the following changes:

New Features:
- Feature Name: description

Improvements:
- Description

Bug Fixes:
- Fixed: description

Full release notes: <link>
```

**Writing rules:**
- Write from the user's perspective - what they can now do, not what code changed
- Group related changes under descriptive headings
- Only include sections that have content (skip empty Breaking Changes, Security, etc.)
- Link PR numbers for easy access to details
- For breaking changes, always include migration instructions with code examples
- Highlight security fixes prominently with CVE IDs when available
- Use consistent tense (past tense: "Added", "Fixed", "Improved")

### Step 4: Publish (if --publish or user confirms)
Show the release notes for review first, then ask:
```
Publish this as a GitHub Release for <tag>? (y/n)
```

If confirmed:
```bash
# Create release
gh release create "<tag>" \
  --title "v1.2.0" \
  --notes "$(cat <<'EOF'
<release-notes-content>
EOF
)"

# Optional flags
--prerelease        # For pre-release versions
--draft             # Save as draft
--target <branch>   # Target branch (default: main)

# Attach artifacts if --attach or artifacts exist
gh release upload "<tag>" dist/*.tar.gz dist/*.zip
```

### Step 5: Report
```
## Release Notes Generated

### Version: <tag>
### Format: <github|slack|email>

### Content Summary
| Section | Entries |
|---|---|
| Highlights | ✓ |
| What's New | N |
| Improvements | N |
| Bug Fixes | N |
| Breaking Changes | N |
| Security | N |
| Contributors | N |

### Status
- GitHub Release: <created|draft|not published>
- Artifacts attached: <list or none>

### Follow-up
- Update CHANGELOG.md: run `/genskills:changelog-gen <version>`
- Bump version in package files if not done
- Announce in team channels
- Monitor for post-release issues
```

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `tagPrefix`: string - version tag prefix (default: "v")
- `includeContributors`: boolean - list contributors (default: true)
- `includeStats`: boolean - include commit/file stats (default: true)
- `autoPublish`: boolean - publish to GitHub without confirmation (default: false)
- `prerelease`: boolean - mark as pre-release by default (default: false)
- `defaultTarget`: "github" | "slack" | "email" - default output format
- `attachArtifacts`: boolean - auto-attach build artifacts (default: false)
- `highlightSecurity`: boolean - prominently flag security fixes (default: true)
