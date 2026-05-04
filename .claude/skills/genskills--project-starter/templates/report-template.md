## Project Created

### <name> - <framework> starter

Location: ./<name>/

### Structure
<tree output of main directories>

### What's Included
- <framework> with <key features>
- <architecture pattern> (if selected)
- <test framework> configured with <coverage threshold>% coverage threshold
- <linter/formatter> configured
- Git initialized with initial commit
- [Security hardening: CSP, CORS, rate limiting, helmet] (if enabled)
- [Observability: structured logging, OpenTelemetry, health checks, Sentry] (if enabled)
- [Database: <orm> with migrations, seed script, connection pooling] (if enabled)
- [Authentication: <provider> with session/JWT management] (if enabled)
- [Docker support with multi-stage build] (if enabled)
- [CI/CD pipeline: lint > test > security > build > e2e > deploy] (if enabled)
- [Deployment config: <target>] (if enabled)
- Developer experience: Husky, lint-staged, commitlint, VS Code config, debug configs, Makefile

### Quick Start
$ cd <name>
$ <dev-command>        # Start development server
$ <test-command>       # Run tests
$ <build-command>      # Build for production
$ make help            # See all available commands

### Next Steps
- Update README.md with project-specific details
- Configure environment variables in .env (copy from .env.example)
- Run `/genskills:env-setup` to verify your environment
- Review and tighten CSP headers for your specific needs
- Set up Sentry DSN and OpenTelemetry endpoint for production
- Configure CI/CD secrets in GitHub repository settings
