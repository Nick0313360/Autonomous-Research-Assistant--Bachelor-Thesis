---
name: genskills:test-generator
description: >
  Generate comprehensive test suites for your code, supporting Jest, Vitest, pytest,
  and other frameworks. Triggers on: "generate tests", "write tests", "add tests",
  "create test", "test this".
user-invocable: true
argument-hint: "[file or function] [--framework jest|vitest|pytest|playwright] [--type unit|integration|e2e]"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(npm test*), Bash(npm run*), Bash(npx vitest*), Bash(npx jest*), Bash(npx playwright*), Bash(pytest*), Bash(cargo test*), Bash(go test*)"
genskills-version: "1.3.0"
genskills-category: "code-quality"
genskills-depends: []
---

# Test Generator

Generate comprehensive, well-structured test suites.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any testing conventions or patterns specified there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (framework overrides, coverage targets, etc.)
- Find existing test files in the project to learn the established patterns (imports, structure, naming, mocking style, assertion library)

### Step 1: Parse Arguments & Analyze Target
Parse `$ARGUMENTS`:
- First positional: file or function to test
- `--framework`: override auto-detected framework - "jest" | "vitest" | "pytest" | "playwright" | "cypress" | "go" | "cargo"
- `--type`: test type - "unit" | "integration" | "e2e" (default: "unit")
- `--coverage`: target coverage percentage (default: from config or 80%)
- `--changed`: generate tests for recently changed code (`git diff --name-only HEAD~1`)

**Analyze target code:**
- Read the file/function completely
- Identify: function signatures, input/output types, return types, side effects, thrown errors
- Map the dependency graph: imports, external service calls, database operations
- Identify pure functions (easy to test) vs. functions with side effects (need mocking)
- Check if tests already exist - augment rather than duplicate

### Step 2: Determine Test Framework
Check in order:
1. `--framework` argument (explicit override)
2. Existing test files - match their framework and patterns
3. Config files:

| Config | Framework |
|---|---|
| `vitest.config.*` | Vitest |
| `jest.config.*` or `jest` in package.json | Jest |
| `playwright.config.*` | Playwright |
| `cypress.config.*` | Cypress |
| `pytest.ini` or `[tool.pytest]` in pyproject.toml | pytest |
| `Cargo.toml` | cargo test |
| `*_test.go` files | go test |

Also detect test utilities already in use:
- Assertion: expect (Jest/Vitest), assert (Node/pytest), should (Chai)
- DOM: @testing-library/react, @testing-library/vue, enzyme
- HTTP: supertest, nock, msw, httpx
- Mocking: jest.mock, vi.mock, unittest.mock, pytest-mock
- Factories: factorybot, fishery, faker

### Step 3: Generate Test Cases
For each function/method, generate tests across categories:

**Happy Path** (at least 2 variations):
- Normal expected inputs → expected outputs
- Different valid input types/shapes
- Common real-world usage patterns

**Edge Cases:**
- Empty inputs: `""`, `[]`, `{}`, `null`, `undefined`, `0`
- Boundary values: max int, min int, empty string, single character
- Special characters, unicode, very long strings
- Large arrays/objects, deeply nested structures
- Concurrent calls, rapid successive calls

**Error Cases:**
- Invalid inputs → expected error/exception
- Thrown exceptions match expected type and message
- Rejected promises with correct error
- Network failures, timeout scenarios
- Missing required fields, wrong types

**Integration Points** (for `--type integration`):
- Database operations: CRUD, transactions, constraint violations
- API calls: success, error status codes, timeout, network failure
- File system: read, write, permissions, missing files
- Mock external dependencies using the project's existing mocking patterns

**Async Behavior:**
- Promise resolution and rejection
- Timeout handling
- Concurrent operations (Promise.all, race conditions)
- Event emitter patterns
- Streaming data

**State Transitions:**
- Before/after states for stateful operations
- React hooks: state changes, effect cleanup
- Store/reducer state mutations
- Database transaction states

**Component Tests** (if React/Vue/Svelte):
- Render with default props
- Render with edge-case props
- User interactions (click, type, submit)
- Conditional rendering (loading, error, empty states)
- Accessibility: correct roles, labels, keyboard navigation
- Snapshot tests only for stable UI (not frequently changing)

### Step 4: Write Tests
**File placement:**
- Follow the project's existing test file naming convention exactly
- Place test files in the expected location (co-located `*.test.*` or `__tests__/` or `test/`)
- Match the import style of existing tests

**Test structure:**
```
describe('ModuleName', () => {
  describe('functionName', () => {
    // Setup
    beforeEach(() => { ... });
    afterEach(() => { ... });

    // Happy path
    it('should return X when given Y', () => { ... });

    // Edge cases
    it('should handle empty input gracefully', () => { ... });

    // Error cases
    it('should throw TypeError when input is invalid', () => { ... });
  });
});
```

**Rules:**
- Use `describe`/`it` or `test` blocks matching existing patterns
- Include setup/teardown (`beforeEach`/`afterEach`) for isolation
- Test names describe **behavior**, not implementation ("should calculate total with tax" not "should call calculateTax")
- Use the project's existing assertion style (expect, assert, should)
- Mock at the right level - mock external boundaries (APIs, DB), not internal functions
- Clean up side effects in afterEach/afterAll
- Avoid test interdependence - each test should be independently runnable
- Use test data factories/builders if the project has them
- Prefer `toEqual` for objects, `toBe` for primitives, `toThrow` for errors

### Step 5: Verify
Run the generated tests:
```bash
npx vitest run <test-file>    # or npx jest <test-file> / pytest <test-file>
```

If any test fails:
1. Read the error output carefully
2. Distinguish between:
   - **Test bug**: fix the test (wrong assertion, missing mock)
   - **Code bug**: report to user (actual behavior doesn't match expected)
3. Fix test bugs and re-run
4. Iterate up to 3 times

Report results:
```
Tests: 15 passed, 0 failed
Coverage: 87% statements, 82% branches
```

### Step 6: Report & Recommendations
```
## Test Generation Report

### Tests Created
- [test-file] N tests for [source-file]
  - N happy path | N edge cases | N error cases | N async | N integration

### Coverage
| Metric | Before | After |
|---|---|---|
| Statements | N% | N% |
| Branches | N% | N% |
| Functions | N% | N% |
| Lines | N% | N% |

### Verification
- All N tests passing ✓
- No flaky tests detected ✓

### Uncovered Code
- [file:line-range] Complex conditional - needs manual test design
- [file:line-range] Error recovery path - requires specific mock setup

### Recommendations
- Add property-based tests for [function] (many input variations)
- Add mutation testing (`npx stryker run`) to verify test quality
- Run `/genskills:code-review` to verify test quality and coverage
- Consider `/genskills:error-boundary` to find untested error paths

### Follow-up
- Suggested test maintenance: keep tests focused on behavior, not implementation
- If refactoring target code, run tests first to verify baseline
```

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `framework`: string - override auto-detected framework
- `coverageTarget`: number - minimum coverage percentage to aim for (default: 80)
- `mockingStrategy`: "minimal" | "comprehensive" - how aggressively to mock
- `testLocation`: "colocated" | "__tests__" | "test/" - where to place test files
- `includeSnapshots`: boolean - generate snapshot tests for components (default: false)
- `testNaming`: "should" | "it" | "descriptive" - test name style preference
