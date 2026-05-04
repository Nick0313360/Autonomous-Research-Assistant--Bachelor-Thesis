---
name: genskills:security-audit
description: >
  Perform a security audit of the codebase, checking for vulnerabilities,
  misconfigurations, and security anti-patterns. Triggers on: "security audit",
  "check security", "find vulnerabilities", "security scan".
user-invocable: true
argument-hint: "[file, directory, or 'full'] [--severity critical|high|medium|low] [--focus owasp|secrets|infra|supply-chain]"
allowed-tools: "Read, Grep, Glob, WebFetch, Bash(git log*), Bash(git diff*), Bash(npm audit*), Bash(pip audit*), Bash(npx *), Bash(docker *), Bash(cargo audit*), Bash(gh *)"
genskills-version: "1.3.0"
genskills-category: "code-quality"
genskills-depends: []
---

# Security Audit

Comprehensive security analysis of the codebase.

## Audit Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any security policies or known exceptions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Identify the tech stack (languages, frameworks, databases, auth providers, cloud services)

### Step 1: Parse Arguments & Scope
Parse `$ARGUMENTS`:
- First positional: file, directory, or "full" for entire project
- `--severity`: minimum severity to report - "critical" | "high" | "medium" | "low" (default: "low")
- `--focus`: limit to specific audit area - "owasp" | "secrets" | "infra" | "supply-chain" | "all" (default: "all")
- `--changed`: only audit files changed recently (`git diff --name-only HEAD~5`)

If no arguments, scan recently changed files by default.

### Step 2: Check for OWASP Top 10 (2021)

**A01 - Broken Access Control:**
- Missing authorization checks on route handlers/API endpoints
- IDOR: direct object references without ownership validation
- Privilege escalation: missing role/permission guards
- Path traversal: user input in file paths without sanitization
- Missing CORS configuration or overly permissive CORS
- Missing CSRF protection on state-changing endpoints

**A02 - Cryptographic Failures:**
- Weak algorithms: MD5/SHA1 for passwords or integrity (should be bcrypt/scrypt/argon2)
- Hardcoded secrets, API keys, encryption keys in source
- Plaintext storage of PII, passwords, tokens in database
- Missing HTTPS enforcement, insecure cookie flags
- Weak JWT secrets (short, predictable), missing algorithm validation
- Missing encryption at rest for sensitive data

**A03 - Injection:**
- SQL injection: string concatenation in queries, unsanitized template literals
- NoSQL injection: user input directly in MongoDB/Firestore queries
- Command injection: user input in `exec()`, `child_process`, `os.system()`
- XSS: unsanitized user input rendered in HTML/templates, `dangerouslySetInnerHTML`
- Template injection: user input in server-side templates (Jinja2, EJS, Handlebars)
- LDAP injection, XML injection, header injection
- Log injection: unsanitized user input in log statements

**A04 - Insecure Design:**
- Missing rate limiting on auth endpoints (login, register, password reset)
- No account lockout after failed login attempts
- Missing CSRF protection on state-changing operations
- Business logic flaws: negative quantities, price manipulation, race conditions in transactions
- Missing input validation on business-critical operations

**A05 - Security Misconfiguration:**
- Debug mode enabled in production (NODE_ENV, DEBUG, Flask debug)
- CORS `*` wildcard allowing all origins
- Missing security headers: CSP, HSTS, X-Frame-Options, X-Content-Type-Options
- Default credentials in configs or environment files
- Verbose error messages exposing stack traces to users
- Directory listing enabled, unnecessary endpoints exposed
- GraphQL introspection enabled in production

**A06 - Vulnerable Components:**
```bash
npm audit --json          # Node.js
pip audit                 # Python
cargo audit               # Rust
```
- Run applicable dependency audit tool
- Check lock file age and known-vulnerable package versions
- Flag dependencies with known CVEs, especially in production deps
- Check for deprecated packages with no security patches

**A07 - Authentication Failures:**
- Hardcoded credentials, default passwords
- Weak JWT secrets, missing token expiry, no refresh token rotation
- Session tokens in URLs or local storage (should be httpOnly cookies)
- Missing password complexity requirements
- Missing MFA on sensitive operations
- Insecure "remember me" implementation
- OAuth: missing state parameter, insecure redirect URI validation

**A08 - Data Integrity Failures:**
- Insecure deserialization: `JSON.parse` on untrusted input without schema validation
- Python: `pickle.loads()`, `yaml.load()` (use `yaml.safe_load()`)
- Missing integrity checks on CI/CD artifacts, auto-update mechanisms
- Unsigned webhooks: processing without signature verification

**A09 - Logging & Monitoring Failures:**
- PII in log statements (emails, passwords, tokens, SSNs, credit cards)
- Missing audit logging for auth events (login, logout, failed attempts, permission changes)
- Sensitive data in error messages returned to users
- Missing request logging for security-relevant endpoints
- Log files with overly permissive access

**A10 - Server-Side Request Forgery (SSRF):**
- User-controlled URLs passed to `fetch`/`axios`/`requests` without allowlist
- Missing URL validation on redirect endpoints
- Internal service URLs constructable from user input
- Missing SSRF protection on file upload (URL-based), webhooks, or import features

### Step 3: Check Secrets & Credentials
- Search for hardcoded secrets using patterns:
  ```
  (?i)(api[_-]?key|secret|password|token|private[_-]?key|access[_-]?key)\s*[=:]\s*['"][^'"]{8,}
  (?i)(ghp_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9_]{36,}
  (?i)(sk-[A-Za-z0-9]{20,})
  (?i)(AKIA[0-9A-Z]{16})
  ```
- Check `.gitignore` covers `.env`, `.env.*`, credentials files, key files (`*.pem`, `*.key`, `*.p12`)
- Verify `.env.example` doesn't contain real values
- Check git history for accidentally committed secrets:
  ```bash
  git log --all --oneline -20 -- '*.env' '*.pem' '*.key' 'credentials*'
  ```
- Check for secrets in Docker build args, CI/CD config, or Terraform variables

### Step 4: Check Infrastructure
- **Docker**: running as root, exposed ports, secrets in Dockerfile/build args, base image vulnerabilities
- **CI/CD**: secret exposure in logs, unsafe artifact handling, untrusted PR code execution
- **Cookie security**: missing `httpOnly`, `secure`, `sameSite` flags
- **TLS**: missing HTTPS enforcement, insecure TLS versions
- **Headers**: missing CSP, HSTS, X-Frame-Options, Permissions-Policy
- **File uploads**: missing type validation, size limits, path traversal in filenames

### Step 5: Supply Chain Checks
- Postinstall scripts in dependencies that execute arbitrary code
- Typosquatting risks (similar package names to popular packages)
- Package integrity (lock file hashes present and consistent)
- Dependency confusion: private package names that could conflict with public registries
- Pinned action versions in GitHub Actions (prefer SHA over tag)

### Step 6: Classify & Generate Report

**Severity Classification:**

| Severity | Criteria | Example |
|---|---|---|
| **Critical** | Actively exploitable, data breach risk | SQL injection, hardcoded production secrets |
| **High** | Exploitable with some effort, significant impact | XSS, missing auth checks, weak crypto |
| **Medium** | Requires specific conditions, moderate impact | CSRF, verbose errors, missing headers |
| **Low** | Informational, minimal direct impact | Missing security best practices |

```
## Security Audit Report

### Critical Vulnerabilities
- [CRITICAL] [CWE-89] [file:line] SQL injection via string concatenation
  → Use parameterized queries: `db.query('SELECT * FROM users WHERE id = $1', [id])`
- [CRITICAL] [CWE-798] [file:line] Hardcoded API key for production service
  → Move to environment variable, rotate the exposed key immediately

### High Risk
- [HIGH] [CWE-79] [file:line] XSS: unsanitized user input in dangerouslySetInnerHTML
  → Use DOMPurify.sanitize() or remove dangerouslySetInnerHTML
- [HIGH] [CWE-862] [file:line] Missing authorization check on admin endpoint
  → Add role verification middleware

### Medium Risk
- [MEDIUM] [CWE-352] [file:line] Missing CSRF token on form submission
  → Add CSRF middleware and token validation
- [MEDIUM] [CWE-16] [file:line] CORS allows all origins (*)
  → Restrict to known domains

### Low Risk / Informational
- [LOW] [file:line] Missing X-Content-Type-Options header
  → Add `nosniff` header to prevent MIME sniffing

### Dependency Vulnerabilities
- [severity] package@version - CVE-XXXX-XXXXX - fix: `npm audit fix` or upgrade

### Secrets & Credentials
- N potential secrets found (values redacted)
- .gitignore coverage: ✓ complete / ⚠️ missing patterns

### Supply Chain
- N postinstall scripts in dependencies
- Lock file integrity: ✓ consistent / ⚠️ missing hashes

### Recommendations (prioritized)
1. [Quick fix] Rotate exposed API key and move to env var
2. [Quick fix] Add parameterized queries for SQL injection
3. [Moderate] Add authorization middleware to admin routes
4. [Significant] Implement CSP headers across the application

### Summary
| Severity | Count |
|---|---|
| Critical | N |
| High | N |
| Medium | N |
| Low | N |

Files scanned: N | Secrets patterns checked: N | Dependencies audited: N

### Follow-up
- Run `/genskills:dependency-audit` for deeper dependency analysis
- Run `/genskills:error-boundary` to find error surfaces that leak sensitive info
- Run `/genskills:test-generator` to add security-focused test cases
```

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `scope`: "full" | "changed" | "critical-paths" - default scan scope
- `ignorePaths`: string[] - paths to skip (e.g., test fixtures, vendor)
- `severityThreshold`: "low" | "medium" | "high" | "critical" - minimum severity to report
- `includeInfra`: boolean - scan Docker/CI configs (default: true)
- `includeSupplyChain`: boolean - run supply chain checks (default: true)
- `secretPatterns`: string[] - additional regex patterns for secret detection
