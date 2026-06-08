---
name: genskills:release
description: >
  End-to-end release automation - bump version, update changelog, tag, create GitHub release, publish.
  Triggers on: "release", "cut release", "publish release", "bump version",
  "new release", "release version".
user-invocable: true
argument-hint: "[version] - e.g., 'patch' or 'minor' or '2.1.0'"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(npm *), Bash(npx *), Bash(git *), Bash(gh *), Bash(python *), Bash(cargo *)"
genskills-version: "1.2.0"
genskills-category: "workflow"
genskills-depends: ["genskills:changelog-gen", "genskills:release-notes"]
---

# Release

Automate the full release workflow from version bump to publish.

## Process

### Step 0: Load Context
- Check `CLAUDE.md` for release conventions, branch strategies, and approval requirements
- Check `${CLAUDE_SKILL_DIR}/_config.json` for preferences
- Verify working directory is clean: `git status --porcelain`

### Step 1: Determine Version
Parse `$ARGUMENTS`:
- `major` / `minor` / `patch` - semver bump from current version
- `premajor` / `preminor` / `prepatch` / `prerelease` - pre-release versions
- `X.Y.Z` - explicit version number

Detect current version from:
- `package.json` (Node.js)
- `pyproject.toml` / `setup.py` (Python)
- `Cargo.toml` (Rust)
- `version.go` or git tags (Go)
- Latest git tag as fallback

If no argument, analyze commits since last release and suggest:
- **patch**: only fixes and chores
- **minor**: new features, no breaking changes
- **major**: breaking changes detected (BREAKING CHANGE in commits)

### Step 2: Pre-Release Checks
Verify before proceeding:

1. **Clean working directory** - no uncommitted changes
2. **On correct branch** - main/master/release branch
3. **Up to date** - `git pull` latest
4. **Tests pass** - `npm test` / `pytest` / `cargo test`
5. **Build succeeds** - `npm run build` / equivalent
6. **No blocking issues** - check CI status on current commit

If any check fails, report and stop:
```
⚠️ Pre-release check failed:
- Tests failing: 2 tests in src/api.test.ts
Fix issues before releasing.
```

### Step 3: Bump Version
Update version in all relevant files:

**Node.js:**
- `package.json` → version field
- `package-lock.json` → regenerate with `npm install`

**Python:**
- `pyproject.toml` → `[project] version`
- `__init__.py` → `__version__`
- `setup.py` → version (if exists)

**Rust:**
- `Cargo.toml` → `[package] version`
- `Cargo.lock` → regenerate with `cargo check`

**Other:**
- Any file matching `version = "X.Y.Z"` pattern
- Update `CHANGELOG.json` or `skills.json` if in this project

### Step 4: Update Changelog
Invoke changelog generation logic:
- Gather commits since last tag
- Categorize by type (feat, fix, docs, etc.)
- Update `CHANGELOG.md` with new version section
- Include date, commit links, and contributor mentions

### Step 5: Create Release Commit and Tag
```bash
git add -A
git commit -m "chore: release v<version>"
git tag -a "v<version>" -m "Release v<version>"
```

**Confirm with user before pushing:**
```
Ready to release v<version>:
- Version bumped in <files>
- Changelog updated
- Commit and tag created

Push to remote and create GitHub release? (y/n)
```

### Step 6: Push and Publish

**Push:**
```bash
git push origin <branch>
git push origin "v<version>"
```

**Create GitHub Release:**
```bash
gh release create "v<version>" --title "v<version>" --notes "<release-notes>"
```

**Publish package (if applicable and user confirms):**
- npm: `npm publish`
- PyPI: `python -m build && twine upload dist/*`
- Crates.io: `cargo publish`
- Go: tag push is sufficient

### Step 7: Report
```
## Release v<version> Complete

### Version
<old-version> → <version>

### Changes Included
- <N> features
- <N> bug fixes
- <N> other changes

### Published
- ✓ Git tag: v<version>
- ✓ GitHub Release: <url>
- ✓ npm registry: <package>@<version>

### What's Next
- Monitor for issues: <link-to-issues>
- Announce release in team channels
- Start next development cycle
```

## Configuration
- `registry`: string - package registry (default: auto-detect)
- `tagPrefix`: string - git tag prefix (default: "v")
- `releaseBranch`: string - branch to release from (default: "main")
- `requireCI`: boolean - require passing CI before release (default: true)
- `autoPublish`: boolean - publish to registry automatically (default: false)
- `changelogStyle`: string - "keep-a-changelog" | "conventional" (default: "keep-a-changelog")
