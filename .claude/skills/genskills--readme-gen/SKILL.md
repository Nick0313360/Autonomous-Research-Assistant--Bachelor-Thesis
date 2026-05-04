---
name: genskills:readme-gen
description: >
  Generate or update a comprehensive README.md for the project.
  Triggers on: "generate README", "create README", "update README",
  "write README", "project README".
user-invocable: true
argument-hint: "[style: minimal|standard|detailed] [--update] [--badges] [--no-toc]"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(git remote*), Bash(git log*), Bash(npm run*), Bash(node *), Bash(gh repo*)"
genskills-version: "1.3.0"
genskills-category: "documentation"
genskills-depends: []
---

# README Generator

Generate a comprehensive project README.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any documentation conventions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Check for existing README.md - **never overwrite without showing a diff first**

### Step 1: Parse Arguments
Parse `$ARGUMENTS`:
- First positional: style - "minimal" | "standard" | "detailed" (default: "standard")
- `--update`: update existing README preserving user-written content
- `--badges`: auto-generate shields.io badges
- `--no-toc`: skip table of contents
- `--section <name>`: only regenerate a specific section
- `--lang <code>`: primary language for examples (default: auto-detect)

### Step 2: Analyze Project
Gather information from multiple sources:

**Project metadata:**
- `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `*.csproj` - name, description, version, license
- `LICENSE` file - license type
- `git remote -v` - repository URL
- `gh repo view --json description,homepageUrl` - GitHub metadata

**Tech stack detection:**

| Source | Information |
|---|---|
| `package.json` dependencies | Frameworks, libraries, runtime |
| `tsconfig.json` / `jsconfig.json` | TypeScript config, path aliases |
| `.nvmrc` / `.node-version` / `.python-version` | Runtime versions |
| `Dockerfile` / `docker-compose.yml` | Container setup, services |
| `.env.example` | Required environment variables |
| `.github/workflows/` | CI/CD pipeline |
| Directory structure | Architecture pattern (monorepo, src/, app/) |

**Existing README analysis (if updating):**
- Parse existing sections and their content
- Identify user-written sections to preserve
- Identify badges, custom HTML, images to keep
- Flag stale content (references to removed deps, wrong commands)

### Step 3: Determine Style & Sections

| Style | Sections | Best For |
|---|---|---|
| **minimal** | Name, description, install, usage | Simple packages, libraries |
| **standard** | All essential sections | Most projects |
| **detailed** | Full docs with architecture, API, contributing | Open-source, team projects |

**Section selection (include only if relevant):**

| Section | minimal | standard | detailed | Condition |
|---|---|---|---|---|
| Title + Description | ✓ | ✓ | ✓ | Always |
| Badges | - | ✓ | ✓ | If `--badges` or CI exists |
| Table of Contents | - | ✓ | ✓ | If >5 sections, unless `--no-toc` |
| Features | - | ✓ | ✓ | If identifiable features |
| Prerequisites | ✓ | ✓ | ✓ | If specific runtime/tools needed |
| Installation | ✓ | ✓ | ✓ | Always |
| Quick Start | ✓ | ✓ | ✓ | Always |
| Usage / Examples | - | ✓ | ✓ | If exports/CLI/API available |
| Configuration | - | ✓ | ✓ | If .env.example or config files |
| Project Structure | - | ✓ | ✓ | If non-trivial structure |
| Architecture | - | - | ✓ | If docs/architecture exists |
| API Reference | - | - | ✓ | If API endpoints exist |
| Development | - | ✓ | ✓ | If dev scripts exist |
| Testing | - | ✓ | ✓ | If test scripts exist |
| Deployment | - | - | ✓ | If deploy config exists |
| Contributing | - | - | ✓ | For open-source projects |
| License | ✓ | ✓ | ✓ | If LICENSE file exists |

### Step 4: Generate README

**Badges (if applicable):**
```markdown
[![CI](https://github.com/owner/repo/actions/workflows/ci.yml/badge.svg)](https://github.com/owner/repo/actions)
[![npm version](https://img.shields.io/npm/v/package-name)](https://npmjs.com/package/package-name)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0-blue)](https://typescriptlang.org)
```

**Content generation rules:**
- Only include sections relevant to the project - don't add empty or placeholder sections
- Use **actual commands** from the project (not generic `npm install` if it uses pnpm/bun)
- Include **real examples** from the codebase, not generic placeholder text
- Detect and use the correct package manager commands:

| Manager | Install | Run | Execute |
|---|---|---|---|
| npm | `npm install` | `npm run` | `npx` |
| yarn | `yarn` | `yarn` | `yarn dlx` |
| pnpm | `pnpm install` | `pnpm` | `pnpm dlx` |
| bun | `bun install` | `bun run` | `bunx` |
| pip | `pip install` | `python -m` | - |
| uv | `uv pip install` | `uv run` | `uvx` |
| cargo | `cargo build` | `cargo run` | - |

- For Configuration section: extract variables from `.env.example` with descriptions
- For Project Structure: use a tree view but only show key directories (not every file)
- For Development: derive from actual `scripts` in package.json
- For Testing: include actual test command and coverage instructions

**Table of Contents:**
```markdown
## Table of Contents
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
- [Usage](#usage)
- [Configuration](#configuration)
- [Development](#development)
- [License](#license)
```
Auto-generate from actual sections present. Skip if `--no-toc`.

### Step 5: Write
**If README.md exists (`--update` mode):**
1. Parse existing sections
2. Identify which sections are stale vs. user-written
3. Show a diff of proposed changes
4. Ask for confirmation before applying
5. Preserve: badges, custom HTML, images, links, user-written prose sections

**If README.md is new:**
- Create the file with all applicable sections
- Show the generated content for review

**Merge strategy for updates:**
- User-written prose → always preserve
- Generated sections (install, dev, structure) → update with current data
- Badges → update URLs, preserve custom badges
- Custom sections (not in template) → always preserve in original position

### Step 6: Report
```
## README Generation Report

### Style: <minimal|standard|detailed>
### Action: <created|updated>

### Sections
| Section | Status |
|---|---|
| Title + Description | ✓ generated |
| Badges | ✓ 4 badges added |
| Features | ✓ 5 features listed |
| Installation | ✓ pnpm commands |
| Quick Start | ✓ with code example |
| Configuration | ✓ 8 env vars documented |
| Project Structure | ✓ tree view |
| Development | ✓ from package.json scripts |
| License | ✓ MIT |

### Preserved (from existing README)
- Custom "Acknowledgements" section
- 2 user-written badges
- Architecture diagram embed

### Follow-up
- Run `/genskills:api-docs` if the project has API endpoints
- Run `/genskills:doc-gen` for inline code documentation
- Run `/genskills:architecture-diagram` to add visual architecture
- Add to CI: verify README links with `npx markdown-link-check README.md`
```

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `style`: "minimal" | "standard" | "detailed" - default style
- `preserveSections`: string[] - section names to never modify (e.g., ["Acknowledgements", "Sponsors"])
- `includeBadges`: boolean - auto-generate shields.io badges (default: true for standard/detailed)
- `includeToc`: boolean - include table of contents (default: true for standard/detailed)
- `packageManager`: string - override detected package manager for commands
- `customSections`: string[] - additional sections to include in template
