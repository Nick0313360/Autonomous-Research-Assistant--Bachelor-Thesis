---
name: genskills:ci-fix
description: >
  Diagnose and fix failing CI/CD pipeline issues. Analyzes build logs,
  test failures, and configuration problems. Triggers on: "fix CI", "CI failing",
  "pipeline broken", "build failed", "GitHub Actions failing".
user-invocable: true
argument-hint: "[CI run URL or 'latest']"
allowed-tools: "Read, Edit, Grep, Glob, Bash(gh *), Bash(git *), Bash(npm test*), Bash(npm run*), Bash(npx *)"
genskills-version: "1.1.0"
genskills-category: "workflow"
genskills-depends: []
---

# CI Fix

Diagnose and fix CI/CD pipeline failures.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - it may document CI/CD specifics
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Identify CI system: `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, `.circleci/`, `bitbucket-pipelines.yml`

### Step 1: Get CI Logs
- If `$ARGUMENTS` contains a URL or run ID, fetch that run's logs
- If `$ARGUMENTS` = "latest" or empty, get the latest failed run:
  `gh run list --status failure --limit 5` then `gh run view <id> --log-failed`
- Identify the failing step, job name, and error messages
- Check if the failure is in the current branch or a different one

### Step 2: Diagnose
Parse the error output and categorize:
- **Test failures**: Read the failing test AND the tested code. Identify if it's a real bug, flaky test, or environment issue
- **Build errors**: TypeScript errors, missing dependencies, syntax issues, webpack/vite config problems
- **Lint failures**: Style violations, import errors - run the linter locally to reproduce
- **Dependency issues**: Lock file conflicts, missing packages, version incompatibilities, resolution failures
- **Environment issues**: Missing env vars/secrets, wrong Node/Python version, missing system deps
- **Timeout**: Slow tests, infinite loops, missing mocks, network calls in tests
- **Permission issues**: Missing secrets, token expiry, insufficient GitHub permissions
- **Flaky failures**: Compare with recent passing runs - `gh run list --limit 10` - same commit passing/failing

### Step 3: Fix
- Apply the fix to the relevant files
- If it's a **real test failure**: fix the code, not the test (unless the test expectation is wrong)
- If it's a **flaky test**: fix the underlying race condition, add proper waits/mocks - avoid retry hacks
- If it's a **config issue**: update the workflow file, document the change
- If it's a **dependency issue**: update lock file, check for peer dep conflicts
- If it's an **env issue**: document the missing variable, suggest adding to CI secrets

### Step 4: Verify Locally
- Run the exact failing command locally to verify the fix
- Check that the fix doesn't break other CI steps: `npm run build && npm test && npm run lint`

### Step 5: Report
```
## CI Fix Report

### Failure Analysis
- CI System: GitHub Actions / GitLab CI / etc.
- Failed Job: job-name
- Failed Step: step-name
- Root Cause: description

### Fix Applied
- [file:line] Description of change

### Local Verification
- Command: `npm test` - PASS/FAIL
- Command: `npm run build` - PASS/FAIL

### Next Steps
- Push fix and monitor CI: `gh run watch`
- If flaky: consider adding `/genskills:test-generator` for more robust tests
```

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `ciSystem`: string - override auto-detected CI system
- `verifyLocally`: boolean - run failing commands locally before fixing (default: true)
- `autoCommit`: boolean - auto-commit the fix (default: false)
