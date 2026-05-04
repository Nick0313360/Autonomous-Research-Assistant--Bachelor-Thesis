---
name: genskills:deploy
description: >
  Guide deployment workflows with pre-deploy checks, build verification,
  and post-deploy monitoring. User-invocable only for safety.
user-invocable: true
disable-model-invocation: true
argument-hint: "[environment: staging|production]"
allowed-tools: "Read, Grep, Glob, Bash(npm run *), Bash(npm test*), Bash(npm audit*), Bash(npx *), Bash(vercel *), Bash(netlify *), Bash(fly *), Bash(docker *), Bash(kubectl *), Bash(aws *), Bash(gcloud *), Bash(terraform *), Bash(git *), Bash(gh *), Bash(pip audit*)"
genskills-version: "1.1.0"
genskills-category: "workflow"
genskills-depends: []
---

# Deploy

Guided deployment workflow with safety checks.

**Note**: This skill is user-invocable only (not auto-triggered) for safety. All deployment commands require explicit user confirmation.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any deployment procedures documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)

### Step 1: Pre-deploy Checklist
Run each check and report pass/fail:
- [ ] No uncommitted changes (`git status`)
- [ ] On the correct branch (not deploying from a feature branch to production)
- [ ] Branch is up to date with remote (`git fetch && git status`)
- [ ] All tests passing (`npm test` or equivalent)
- [ ] Build succeeds locally (`npm run build` or equivalent)
- [ ] No critical/high dependency vulnerabilities (`npm audit --audit-level=high`)
- [ ] No merge conflicts with the default branch

**If any check fails, stop and report the issue.** Do NOT proceed with deployment.

### Step 2: Identify Deploy Method
Check the project for (in order):
- Custom deploy scripts in `package.json` (`deploy`, `deploy:staging`, `deploy:production`) - **prefer these**
- `vercel.json` / `.vercel/` → Vercel (`vercel` / `vercel --prod`)
- `netlify.toml` → Netlify (`netlify deploy` / `netlify deploy --prod`)
- `fly.toml` → Fly.io (`fly deploy`)
- `.github/workflows/deploy*` → GitHub Actions (trigger via `gh workflow run`)
- `Dockerfile` / `docker-compose.yml` → Docker-based
- `Procfile` → Heroku
- `kubectl` / k8s manifests → Kubernetes
- AWS CDK / SAM / CloudFormation templates → AWS
- `gcloud` / `app.yaml` → Google Cloud
- `terraform/` → Terraform (plan first, then apply)

### Step 3: Execute Deploy
**Always confirm with the user before executing ANY deployment command.**

Environment from `$ARGUMENTS`:
- `staging` (default): Deploy to staging/preview environment
- `production`: Deploy to production - **requires double confirmation**: show the exact command and ask "Are you sure you want to deploy to PRODUCTION?"

For production deploys, also verify:
- The staging deployment has been tested
- No recent incidents or active incidents

### Step 4: Post-deploy Verification
- Verify the deployment succeeded (check deploy output for errors)
- Show the deployed URL if available
- Run a basic health check if the URL is known (`curl` or equivalent)
- Check deployment status via platform CLI if available

### Step 5: Report
```
## Deployment Report

### Environment: staging / production
### Method: Vercel / Docker / etc.
### Status: SUCCESS / FAILED

### Pre-deploy Checks
- ✓ Tests passing
- ✓ Build succeeded
- ✓ No uncommitted changes
- ✗ Issue (if any)

### Deployed URL
- https://...

### Rollback Instructions
- If issues found: <specific rollback command for the platform>

### Monitoring
- Check logs: <platform-specific log command>
- Dashboard: <if known>
```

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `defaultEnvironment`: "staging" | "production" - default deploy target
- `deployScript`: string - custom deploy command override
- `requireTests`: boolean - require all tests to pass before deploy (default: true)
- `requireCleanWorkdir`: boolean - require no uncommitted changes (default: true)
