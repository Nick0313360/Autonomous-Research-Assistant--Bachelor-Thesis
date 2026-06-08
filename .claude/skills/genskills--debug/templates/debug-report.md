## Debug Report

### Problem
- Error: <error type and message>
- Location: [file:line]
- Trigger: <what causes it>
- Severity: <crash | incorrect behavior | performance | data corruption>
- Frequency: <one-off | intermittent | escalating | constant>

### Investigation Timeline
- <what was checked and eliminated>
- <key evidence that pointed to root cause>

### Root Cause
<Clear explanation of why this happened - not what, but WHY>

### Fix Applied
- [file:line] Description of change
- Scope of change: <minimal | moderate | significant>

### Verification
- Command: <what was run> - PASS/FAIL
- Edge cases tested: <list>

### Prevention
- Suggested test to add to prevent regression
- Run `/genskills:test-generator <file>` to add a regression test
- Related code that might have the same issue: [file:line]
- Systemic improvements: <better typing, validation layer, monitoring alert>
