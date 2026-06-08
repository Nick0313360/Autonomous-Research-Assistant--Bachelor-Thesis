---
name: genskills:accessibility-audit
description: >
  Audit components for accessibility issues - missing alt text, ARIA roles,
  keyboard navigation, color contrast, semantic HTML. Triggers on: "accessibility check",
  "a11y audit", "accessibility", "wcag", "screen reader".
user-invocable: true
argument-hint: "[file or directory] [--level A|AA|AAA] [--fix] [--framework react|vue|svelte|angular]"
allowed-tools: "Read, Edit, Grep, Glob, Bash(npx *), Bash(npm run*), Bash(git diff*)"
genskills-version: "1.3.0"
genskills-category: "code-quality"
genskills-depends: []
---

# Accessibility Audit

Check codebase for WCAG 2.2 accessibility compliance.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any a11y standards documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Identify the UI framework (React, Next.js, Vue, Nuxt, Svelte, SvelteKit, Angular, Astro, plain HTML)

### Step 1: Parse Arguments
Parse `$ARGUMENTS`:
- First positional: file or directory to audit
- `--level`: WCAG target level - "A" | "AA" | "AAA" (default: "AA")
- `--fix`: automatically apply simple fixes (add alt, labels, ARIA attributes)
- `--framework`: override auto-detected UI framework
- `--changed`: only audit files changed since last commit (`git diff --name-only HEAD~1`)

If no arguments, scan all component/page files (`**/*.tsx`, `**/*.jsx`, `**/*.vue`, `**/*.svelte`, `**/*.astro`).

### Step 2: Check for Existing a11y Tooling
Before manual analysis, check what's already configured:
- `eslint-plugin-jsx-a11y` → run `npx eslint --plugin jsx-a11y` if available
- `@axe-core/react` or `@axe-core/playwright` → note runtime checks exist
- `pa11y` or `lighthouse` in CI/CD → note automated checks
- `biome` a11y rules → check `biome.json` for lint/a11y config
- Note which issues are already covered by tooling (skip those in manual analysis)

### Step 3: Static Analysis
Check for common a11y issues across categories:

**Images & Media**:
- `<img>` without `alt` attribute
- Decorative images without `alt=""` and `role="presentation"`
- `<video>` / `<audio>` without captions/transcripts
- Icon-only buttons without accessible labels (`aria-label` or visually hidden text)
- SVG icons without `aria-hidden="true"` or `role="img"` with `<title>`
- `next/image` or framework image components without alt
- Background images conveying information without text alternative

**Semantic HTML**:
- `<div>` or `<span>` used as buttons/links (should be `<button>` / `<a>`)
- Missing heading hierarchy (h1 → h3 without h2)
- Multiple `<h1>` elements on a single page/route
- Missing `<main>`, `<nav>`, `<header>`, `<footer>` landmarks
- Tables without `<th>`, `scope`, or `<caption>` attributes
- Lists not using `<ul>` / `<ol>` / `<li>`
- Missing `lang` attribute on `<html>`
- Missing `<title>` in `<head>` or dynamic page titles
- Using `<br>` for spacing instead of CSS

**Forms**:
- `<input>` without associated `<label>` or `aria-label`/`aria-labelledby`
- Missing form validation error announcements (`aria-describedby` pointing to error)
- Missing `required` attribute or `aria-required`
- Missing `autocomplete` attribute on common fields (name, email, address, phone)
- Form errors not programmatically associated with inputs
- Missing `<fieldset>`/`<legend>` for radio/checkbox groups
- Submit buttons with no discernible text
- Search inputs without `role="search"` on form or landmark

**Keyboard Navigation**:
- Click handlers on non-interactive elements without `tabIndex`, `role`, and `onKeyDown`/`onKeyPress`
- Missing focus styles (`:focus-visible` or equivalent)
- Focus traps in modals/dialogs (focus should be trapped inside and restored on close)
- Skip-to-content link presence
- Custom components (dropdowns, tabs, carousels, date pickers) missing keyboard support
- Positive `tabIndex` values (should be 0 or -1 only)
- `<dialog>` elements without proper focus management
- Popover API usage without keyboard dismiss handling
- Scroll containers without keyboard scrolling support

**ARIA**:
- Incorrect ARIA roles for the element type
- Missing `aria-live` for dynamic content updates (toasts, alerts, loading states, real-time data)
- Missing `aria-expanded` on toggles/accordions/dropdowns
- Missing `aria-label` on icon buttons and ambiguous links ("click here", "read more")
- Redundant ARIA (e.g., `role="button"` on `<button>`, `role="link"` on `<a>`)
- `aria-hidden="true"` on focusable elements (accessibility trap)
- Missing `aria-current="page"` on active navigation links
- Missing `aria-describedby` for complex form instructions
- Missing `aria-busy` / `aria-live="polite"` for loading states

**Color & Contrast**:
- Text colors that may have insufficient contrast (flag hardcoded colors < 4.5:1 for normal text, < 3:1 for large text)
- Information conveyed by color alone without alternative indicator (icons, underlines, patterns)
- Disabled states that are too low contrast to read
- Focus indicators with insufficient contrast (< 3:1 against adjacent colors)
- CSS-in-JS / Tailwind classes with potential contrast issues (e.g., `text-gray-400` on white)

**Motion & Animation**:
- Missing `prefers-reduced-motion` media query for animations/transitions
- Auto-playing content without pause/stop controls
- Parallax effects without reduced-motion alternative
- CSS animations without `@media (prefers-reduced-motion: reduce)` fallback

**Touch & Mobile**:
- Touch targets smaller than 44x44px (WCAG 2.2 Target Size)
- Hover-only interactions without touch/focus alternative
- Swipe-only actions without button alternative

### Step 4: Classify Findings

| Severity | WCAG Level | Meaning | Example |
|---|---|---|---|
| **Critical** | A violation | Blocks users from accessing content | Missing alt text, no keyboard access |
| **Serious** | AA violation | Significant barrier to usability | Missing labels, insufficient contrast |
| **Moderate** | AA best practice | Degraded experience | Heading hierarchy skip, missing landmarks |
| **Minor** | AAA / enhancement | Improvement opportunity | Missing aria-current, touch target size |

### Step 5: Generate Report
```
## Accessibility Audit Report (WCAG 2.2 Level <target>)

### Critical (Level A violations) - must fix
- [file:line] <img> missing alt attribute → add descriptive alt text
- [file:line] <div onClick> should be <button> with keyboard handler

### Serious (Level AA violations) - should fix
- [file:line] Input without associated label → add <label htmlFor>
- [file:line] Missing skip-to-content link → add as first focusable element
- [file:line] Text contrast ratio 3.2:1 (requires 4.5:1) → darken text color

### Moderate - recommended
- [file:line] Heading hierarchy skip (h1 → h3) → add missing h2
- [file:line] aria-label missing on icon button

### Minor - nice to have
- [file:line] Touch target 32x32px → increase to 44x44px minimum

### Automated Tooling Status
- eslint-plugin-jsx-a11y: <installed|not installed>
- axe-core: <installed|not installed>
- CI accessibility checks: <configured|not configured>

### Tooling Recommendations
- Install eslint-plugin-jsx-a11y for compile-time catching
- Add @axe-core/react for runtime dev checks
- Add pa11y or lighthouse to CI for regression prevention
- Add playwright-axe for integration test coverage

### Summary
- X critical, Y serious, Z moderate, W minor issues
- WCAG 2.2 Level <target> estimated compliance: X%
- Files scanned: N | Components audited: N

### Follow-up
- Run `/genskills:code-review` to verify a11y fixes don't break functionality
- Run `/genskills:test-generator` to add a11y-specific tests
```

### Step 6: Auto-fix (if --fix)
If `--fix` flag is set, apply safe automatic fixes:
- Add empty `alt=""` to decorative images
- Add `aria-hidden="true"` to decorative SVGs
- Add `role="button"` and `tabIndex={0}` to click-handler divs
- Add `<label>` associations for obvious input/label pairs
- Add `aria-label` to icon-only buttons using icon name
- Wrap form groups in `<fieldset>` with `<legend>`

**Do NOT auto-fix:**
- Alt text that requires understanding the image content (flag for manual entry)
- Color contrast (requires design decisions)
- Complex keyboard navigation patterns
- Focus management in modals/dialogs

After fixes, re-run analysis to verify improvements.

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `wcagLevel`: "A" | "AA" | "AAA" - target compliance level (default: "AA")
- `framework`: string - override auto-detected UI framework
- `ignorePaths`: string[] - paths to skip
- `autoFix`: boolean - automatically apply simple fixes (default: false)
- `includeToolingSetup`: boolean - include setup instructions for a11y tooling (default: true)
- `touchTargetSize`: number - minimum touch target in px (default: 44)
