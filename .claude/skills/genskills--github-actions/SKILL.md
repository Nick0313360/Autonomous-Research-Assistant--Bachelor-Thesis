---
name: genskills:github-actions
description: >
  Generate and fix GitHub Actions workflows - CI/CD, matrix builds, deployment pipelines.
  Triggers on: "github actions", "github workflow", "CI pipeline", "CD pipeline",
  "create workflow", "actions yaml".
user-invocable: true
argument-hint: "[type] - e.g., 'ci' or 'deploy' or 'release' or 'full'"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(gh *), Bash(git *), Bash(npm *)"
genskills-version: "1.2.0"
genskills-category: "devops"
genskills-depends: []
---

# GitHub Actions

Generate production-ready GitHub Actions workflows.

## Process

### Step 0: Load Context
- Check `CLAUDE.md` for CI/CD conventions, deployment targets, required checks
- Check `${CLAUDE_SKILL_DIR}/_config.json` for preferences
- Check existing `.github/workflows/` - don't overwrite without asking

### Step 1: Parse Arguments
Parse `$ARGUMENTS`:
- `ci` - continuous integration (lint, test, build)
- `deploy` - deployment pipeline
- `release` - release automation
- `pr-checks` - PR validation (labels, size, conventional commits)
- `scheduled` - cron-based tasks (dependency updates, audits)
- `full` - generate all applicable workflows
- `fix` - fix existing broken workflows

### Step 2: Detect Project Stack
- Language and runtime version (Node.js 20, Python 3.12, Go 1.22, etc.)
- Package manager and lockfile
- Test framework and test command
- Build command and output directory
- Deployment target (Vercel, AWS, GCP, Docker registry, npm)
- Monorepo structure (affects job matrix)

### Step 3: Generate Workflows

**CI Workflow** (`.github/workflows/ci.yml`):
```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'npm'
      - run: npm ci
      - run: npm run lint
      - run: npm run typecheck

  test:
    runs-on: ubuntu-latest
    needs: lint
    strategy:
      matrix:
        node-version: [18, 20, 22]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node-version }}
          cache: 'npm'
      - run: npm ci
      - run: npm test -- --coverage
      - uses: actions/upload-artifact@v4
        if: matrix.node-version == 20
        with:
          name: coverage
          path: coverage/

  build:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'npm'
      - run: npm ci
      - run: npm run build
      - uses: actions/upload-artifact@v4
        with:
          name: build
          path: dist/
```

Tailor to detected stack:
- **Python**: use `actions/setup-python`, pip cache, pytest, ruff
- **Go**: use `actions/setup-go`, go test, golangci-lint
- **Rust**: use `dtolnay/rust-toolchain`, cargo test, clippy
- **.NET**: use `actions/setup-dotnet`, dotnet test

**Deploy Workflow** (`.github/workflows/deploy.yml`):
```yaml
name: Deploy

on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      environment:
        type: choice
        options: [staging, production]

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: ${{ github.event.inputs.environment || 'staging' }}
    steps:
      - uses: actions/checkout@v4
      # Build steps...
      # Deploy to target...
```

Deployment targets:
- **Vercel**: use `amondnet/vercel-action`
- **AWS ECS**: use `aws-actions/amazon-ecs-deploy-task-definition`
- **Docker**: build and push to GHCR/DockerHub/ECR
- **npm**: `npm publish`
- **GitHub Pages**: `actions/deploy-pages`

**Release Workflow** (`.github/workflows/release.yml`):
```yaml
name: Release

on:
  push:
    tags: ['v*']

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Generate release notes
        run: gh release create ${{ github.ref_name }} --generate-notes
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

**PR Checks** (`.github/workflows/pr-checks.yml`):
```yaml
name: PR Checks

on:
  pull_request:
    types: [opened, edited, synchronize]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: amannn/action-semantic-pull-request@v5
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### Step 4: Best Practices
- **Concurrency**: cancel in-progress runs for same branch
- **Caching**: cache dependencies (npm, pip, go mod, cargo)
- **Matrix**: test across runtime versions
- **Artifacts**: upload build output and coverage
- **Secrets**: use GitHub Secrets, never hardcode
- **Permissions**: use minimal `permissions` block
- **Pinned actions**: use full SHA or major version tag
- **Timeouts**: set `timeout-minutes` to prevent hung jobs
- **Conditions**: skip CI for docs-only changes

### Step 5: Validate
- Check YAML syntax is valid
- Verify referenced actions exist at specified versions
- Check that referenced scripts exist in package.json
- Verify secrets are documented

### Step 6: Report
```
## GitHub Actions Workflows Generated

### Workflows
- ci.yml - Lint → Test (matrix) → Build
- deploy.yml - Auto-deploy to staging on main push
- release.yml - Create GitHub Release on tag push

### Triggers
- Push to main: CI + Deploy to staging
- Pull request: CI only
- Tag v*: Release
- Manual: Deploy to production (workflow_dispatch)

### Required Secrets
- VERCEL_TOKEN - deployment token
- CODECOV_TOKEN - coverage upload (optional)

### Setup
1. Add secrets in GitHub → Settings → Secrets → Actions
2. Enable "Allow GitHub Actions" in repo settings
3. Push to main to trigger first CI run

### Next Steps
- Add branch protection requiring CI to pass
- Configure deployment environments in GitHub Settings
- Add status badges to README
```

## Configuration
- `runner`: string - "ubuntu-latest" | "self-hosted" (default: "ubuntu-latest")
- `deployTarget`: string - "vercel" | "aws" | "gcp" | "docker" | "npm"
- `testMatrix`: boolean - test across multiple versions (default: true)
- `cacheStrategy`: string - "npm" | "pnpm" | "yarn" (default: auto-detect)
- `skipCIPatterns`: string[] - file patterns that skip CI (default: ["*.md", "docs/**"])
