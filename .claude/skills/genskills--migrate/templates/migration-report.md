## Migration Report

### Migration: <library> <from> → <to>

### Changes Summary
- Dependencies updated: N
- Config files modified: N
- Source files modified: N
- Tests updated: N
- Codemods applied: N

### Automated Changes
- Codemod applied: description
- AST transform applied: description

### Manual Changes
- [file:line] Description of change and why

### Dependency Conflicts Resolved
- <package>: <conflict description> → <resolution>

### Verification
- Build: PASS/FAIL
- Tests: PASS/FAIL (N passing, N failing)
- Lint: PASS/FAIL
- Type Check: PASS/FAIL
- Visual Regression: PASS/FAIL/SKIPPED

### Rollback Plan
- Git tag: pre-migration-<name>
- Feature flag: <flag-name> (if applicable)
- Database rollback: <script-name> (if applicable)

### Remaining Manual Steps
- Items that need human review or testing

### Follow-up
- Run `/genskills:test-generator` to add tests for migrated code
- Run `/genskills:lint-fix` to clean up any formatting issues
- Schedule removal of old code paths after confidence period
- Rotate any credentials exposed to the old system
