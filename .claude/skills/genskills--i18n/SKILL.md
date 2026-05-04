---
name: genskills:i18n
description: >
  Manage internationalization - extract hardcoded strings, generate translation
  keys, validate locale files for missing keys. Triggers on: "extract strings",
  "i18n", "translations", "missing translations", "internationalization", "localize".
user-invocable: true
argument-hint: "[action: extract|validate|add-locale|export|import|audit-rtl|pseudo-loc|namespace] [file or locale]"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(npx *), Bash(npm run*)"
genskills-version: "1.4.2"
genskills-category: "development"
genskills-depends: []
---

# Internationalization (i18n)

Comprehensive internationalization management: string extraction, translation validation, ICU message format handling, RTL support, translation workflow integration, namespace management, locale-aware formatting, and SSR/SSG locale strategies.

## Process

### Step 0: Load Project Context
- Check for `CLAUDE.md` at the project root - follow any i18n conventions documented there
- Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences (see Configuration below)
- Identify the project's rendering strategy (CSR, SSR, SSG, ISR) as it affects locale handling

### Step 1: Detect i18n Setup

Check for (in priority order):
- `next-intl` → Next.js i18n (App Router)
- `next-i18next` → Next.js i18n (Pages Router)
- `react-intl` / `react-i18next` → React i18n
- `vue-i18n` → Vue i18n
- `@angular/localize` → Angular i18n
- `svelte-i18n` → Svelte i18n
- `@lingui/core` → Lingui i18n
- `typesafe-i18n` → Type-safe i18n
- `paraglide-js` → Inlang Paraglide
- `messages/`, `locales/`, `translations/`, `lang/` directories → translation files
- `i18n.ts` / `i18n.config.*` → i18n configuration

Identify:
- Default locale and all available locales
- Translation file format: JSON, YAML, TypeScript, PO, XLIFF, ARB
- The translation function name: `t()`, `formatMessage()`, `$t()`, `useTranslations()`, `msg()`, `i18n._()`
- Whether ICU MessageFormat is used (look for `{count, plural, ...}` or `{gender, select, ...}` patterns)
- Namespace strategy: single file per locale, split by feature/route, nested objects
- RTL locales in use: Arabic (`ar`), Hebrew (`he`), Persian/Farsi (`fa`), Urdu (`ur`), Pashto (`ps`), Sindhi (`sd`), Kurdish Sorani (`ckb`), Uyghur (`ug`), Dhivehi (`dv`), Yiddish (`yi`)
- URL i18n strategy: path prefix (`/en/about`), subdomain (`en.site.com`), query param (`?lang=en`), cookie/header based
- Rendering mode per route: SSR, SSG, ISR, CSR - affects how locale is resolved and cached

### Step 2: Execute Action

---

#### `extract` (default)

Scan source files for hardcoded user-facing strings, with full awareness of context and string category.

**String categories to extract** (tag each extracted string with its category):

| Category | Examples | Key prefix suggestion |
|---|---|---|
| UI labels | Button text, form labels, headings, menu items | `ui.*`, `common.*` |
| Error messages | Validation errors, API errors, 404/500 text | `errors.*` |
| Toast/notification text | Success/warning/info messages | `notifications.*` |
| Placeholder text | Input placeholders, empty states, search hints | `placeholders.*` |
| Accessibility labels | `aria-label`, `aria-describedby`, `alt` text, `title` attributes, `role` descriptions | `a11y.*` |
| SEO/metadata | `<title>`, `<meta name="description">`, Open Graph text, JSON-LD strings | `meta.*`, `seo.*` |
| Email templates | Subject lines, body text, CTA buttons | `emails.*` |
| PDF/document content | Generated PDF text, export content, print layouts | `documents.*` |
| Push notifications | Notification titles and bodies | `push.*` |
| Legal/policy text | Terms, privacy policy, cookie consent | `legal.*` |
| Dates/times displayed as text | "Last updated on", "Created", relative time labels | `datetime.*` |

**Skip**: classNames, CSS values, URLs, config values, code identifiers, log messages (unless user-facing), comments, test assertions, enum values used as code identifiers, environment variable names, file paths, regex patterns, color hex codes, technical IDs

**Skip**: strings already wrapped in `t()` or equivalent

**Extraction for dynamic strings with interpolation**:
- Detect string templates: `` `Hello ${name}` `` → `t('greeting', { name })`
- Detect concatenation: `"Hello " + name` → `t('greeting', { name })`
- Detect JSX interpolation: `<p>Hello {user.name}</p>` → `<p>{t('greeting', { name: user.name })}</p>`
- Preserve interpolation variables as ICU placeholders: `"Hello {name}"`

**ICU MessageFormat generation**:
- When a string involves a count/number, generate plural form:
  ```
  {count, plural,
    =0 {No items}
    one {# item}
    other {# items}
  }
  ```
- When a string involves gender or selection, generate select form:
  ```
  {gender, select,
    male {He liked your post}
    female {She liked your post}
    other {They liked your post}
  }
  ```
- For number formatting: `{amount, number, currency}`, `{percent, number, percent}`
- For date/time formatting: `{date, date, medium}`, `{time, time, short}`
- Support nested ICU messages when needed:
  ```
  {gender, select,
    male {{count, plural, one {He has # item} other {He has # items}}}
    female {{count, plural, one {She has # item} other {She has # items}}}
    other {{count, plural, one {They have # item} other {They have # items}}}
  }
  ```

**Key generation**:
- Detect the project's existing naming convention: `namespace.key`, `page.section.key`, flat keys, etc.
- Use consistent casing matching existing keys: `kebab-case`, `camelCase`, `snake_case`
- Group keys by category/feature namespace
- Avoid overly generic keys - prefer `checkout.submitOrder` over `common.submit` when context-specific
- For duplicate English text in different contexts, generate distinct keys: `button.close` vs `dialog.close` vs `nav.close`

**Create entries in translation files for the default locale, then replace hardcoded strings with the appropriate translation function calls.**

---

#### `validate`

Comprehensive validation across all locales and translation files.

**Key completeness**:
- Load all locale files
- Compare keys across all locales - use the default locale as the reference
- Report missing keys per locale (keys in default but not in target)
- Report extra keys per locale (keys in target but not in default - possibly stale)
- Report unused keys (keys in translation files but not referenced anywhere in code)
- Report keys with identical values across unrelated locales (possible untranslated - but skip English/similar language pairs like en/en-GB)

**Interpolation and placeholder consistency**:
- Ensure every `{variable}` placeholder in the default locale exists in all translations
- Ensure no extra placeholders were introduced in translations that don't exist in the default
- Verify ICU placeholder types match: if default has `{count, number}`, translation must too
- Check that HTML tags in translations match the default (opening/closing tag balance)

**ICU syntax validation**:
- Parse all ICU MessageFormat strings for syntax errors
- Verify plural categories are valid for the target locale's CLDR rules:
  - Arabic (`ar`): requires zero, one, two, few, many, other
  - Russian (`ru`): requires one, few, many, other
  - Japanese (`ja`), Chinese (`zh`), Korean (`ko`), Vietnamese (`vi`): only `other`
  - English (`en`): one, other
  - Polish (`pl`): one, few, many, other
  - French (`fr`): one, many, other (as of CLDR 42+)
- Validate select/selectordinal options are present
- Check for unescaped special characters in ICU: `{`, `}`, `#`, `'` - must be `'{literal}'`
- Validate nested ICU messages for balanced braces

**HTML and XSS risk detection**:
- Flag translations containing `<script>`, `onclick=`, `javascript:`, `onerror=`, or other event handlers
- Warn about `<a href="...">` where the href differs from the default locale (possible phishing)
- Warn about raw HTML in translations - recommend using rich text components (`<Trans>`, `RichText`) instead
- Flag translations that introduce HTML tags not present in the default locale

**Terminology and glossary enforcement**:
- If a glossary file exists (`${CLAUDE_SKILL_DIR}/glossary.json` or project-level), validate that key terms are translated consistently
- Flag when the same source term has multiple different translations within one locale
- Flag when brand names or product names are incorrectly translated (should usually be kept as-is)

**Character length validation**:
- Warn when translations exceed expected expansion ratios relative to English:
  - German (`de`): ~30% longer
  - Finnish (`fi`): ~30-40% longer
  - French (`fr`): ~15-20% longer
  - Italian (`it`): ~15% longer
  - Spanish (`es`): ~15-25% longer
  - Japanese (`ja`): can be 10-55% shorter (but wider characters)
  - Chinese (`zh`): can be 30-50% shorter
  - Korean (`ko`): can be 10-15% shorter
  - Arabic (`ar`): ~25% longer
  - Russian (`ru`): ~20-30% longer
  - Thai (`th`): can be 15% longer with much taller line height
- Flag translations that are suspiciously short (likely untranslated or truncated)
- Flag translations that are dramatically longer than expected (may cause UI overflow)

**Locale-specific format validation**:
- Date formats: verify locale-appropriate patterns (MM/DD/YYYY for en-US, DD/MM/YYYY for en-GB, YYYY-MM-DD for ISO/ja/ko)
- Number formats: decimal separator (`.` vs `,`), thousands separator (`,` vs `.` vs ` `)
- Currency: symbol placement (prefix vs suffix), spacing, symbol correctness
- Verify that hardcoded date/number formats are not embedded in translation strings - they should use ICU format functions

---

#### `add-locale`

Add a new locale to the project.

- Parse `$1` as the locale code (e.g., `es`, `fr`, `de`, `ja`, `ar`, `zh-Hans`, `pt-BR`)
- Validate locale code against IETF BCP 47 / CLDR - warn if code looks invalid
- Copy default locale file(s) as template
- Create new locale file(s) with all keys, values set to the default locale values
- Add a comment or marker indicating values need translation: prefix values with `[NEEDS_TRANSLATION]` or use a `_meta.untranslated: true` flag
- Update i18n config to include the new locale
- Update any locale switcher/dropdown if detectable
- If the locale is RTL (ar, he, fa, ur, ps, sd, ckb, ug, dv, yi):
  - Set `dir="rtl"` in the HTML or layout config
  - Add the locale to any RTL locale list in the project
  - Warn about potential RTL layout issues and suggest running `audit-rtl`
- If the locale uses a non-Latin script, verify font support in the project:
  - CJK: check for CJK-capable font stack
  - Arabic/Hebrew: check for RTL-capable fonts
  - Thai: check for Thai-capable fonts with proper line-height
  - Devanagari, Bengali, Tamil, etc.: check for Indic font support
- For SSG projects: ensure the new locale is included in static generation paths (`generateStaticParams`, `getStaticPaths`, etc.)
- For SSR projects: verify the locale is handled in middleware/server-side routing
- Update `sitemap.xml` generation if present to include the new locale
- Add `hreflang` link tags for the new locale if not auto-generated

---

#### `export`

Export translations for external translation tools and services.

**XLIFF export** (XML Localization Interchange File Format):
- Generate XLIFF 1.2 or 2.0 files from the project's translation files
- Include source language and target language attributes
- Mark untranslated segments as `state="new"` or `state="needs-translation"`
- Preserve ICU message syntax within translation units
- Include context notes where available (key path, file location, screenshot reference)

**PO/POT export** (GNU gettext):
- Generate `.pot` template file from default locale
- Generate `.po` files per target locale with existing translations filled in
- Map ICU placeholders to PO-compatible format where possible
- Include `msgctxt` for disambiguation when keys share the same English text

**CSV export**:
- Generate a flat CSV: `key, context, en, es, fr, de, ...`
- Include a `status` column: `translated`, `needs-translation`, `needs-review`
- Escape any commas, quotes, or newlines in translation values
- Optionally include character count and max-length columns

**Machine translation placeholder generation**:
- When exporting untranslated keys, optionally generate machine translation placeholders
- **Always** mark machine-translated values clearly: prefix with `[MT]` or set a metadata flag
- Warn: "Machine translations are placeholders only. Professional review is required before shipping."
- Preserve ICU placeholders and HTML tags - do not translate `{variable}` or `<tag>` tokens
- Suggest using translation memory from existing translations to fill in repeated phrases

---

#### `import`

Import translations from external tools back into the project.

- Detect import file format: XLIFF, PO, CSV, JSON, YAML, ARB
- Map imported keys back to the project's translation file structure
- Handle key format differences (flat vs nested, different separators)
- Validate imported translations:
  - ICU syntax check on all imported values
  - Placeholder consistency check against default locale
  - HTML/XSS risk scan
  - Character encoding verification (UTF-8, no BOM issues)
- Report: new translations added, updated translations, skipped entries (with reasons)
- Back up existing translation files before overwriting
- Merge strategy: only update keys that were previously untranslated or marked for review (never overwrite manually edited translations without confirmation)

---

#### `audit-rtl`

Audit the project for RTL (right-to-left) language support.

**Detect RTL readiness**:
- Check if any configured locale is RTL
- Verify `dir` attribute handling: `<html dir="rtl">` or dynamic `dir` attribute based on locale
- Check for `document.documentElement.dir` or equivalent in client-side locale switching

**CSS logical properties audit**:
Scan all CSS/SCSS/styled-components/Tailwind for physical properties that should be logical:

| Physical (problematic) | Logical (correct) |
|---|---|
| `margin-left` / `margin-right` | `margin-inline-start` / `margin-inline-end` |
| `padding-left` / `padding-right` | `padding-inline-start` / `padding-inline-end` |
| `border-left` / `border-right` | `border-inline-start` / `border-inline-end` |
| `left` / `right` (positioning) | `inset-inline-start` / `inset-inline-end` |
| `text-align: left` / `right` | `text-align: start` / `end` |
| `float: left` / `right` | `float: inline-start` / `inline-end` |
| `border-radius: 4px 0 0 4px` | `border-start-start-radius` / etc. |

For Tailwind projects, check for:
- `ml-*` / `mr-*` → should be `ms-*` / `me-*`
- `pl-*` / `pr-*` → should be `ps-*` / `pe-*`
- `left-*` / `right-*` → should be `start-*` / `end-*`
- `text-left` / `text-right` → should be `text-start` / `text-end`
- `rounded-l-*` / `rounded-r-*` → should be `rounded-s-*` / `rounded-e-*`
- `border-l-*` / `border-r-*` → should be `border-s-*` / `border-e-*`

**Bidirectional text handling**:
- Check for proper use of `<bdi>` elements for user-generated content within RTL contexts
- Check for `unicode-bidi` and `direction` CSS properties
- Verify that mixed LTR/RTL content (e.g., English brand names in Arabic text) uses proper bidi isolation
- Check for `Intl.Segmenter` or equivalent for proper text segmentation in RTL scripts

**RTL-specific layout issues**:
- Icons that imply direction (arrows, back buttons, progress indicators) - these need mirroring
- Check for `transform: scaleX(-1)` or `[dir="rtl"]` selectors for directional icons
- Swipe gestures and horizontal scroll - direction may need inverting
- Check for hardcoded `translateX` values that assume LTR
- Verify text truncation with ellipsis works correctly in RTL
- Phone number and numeric input fields should remain LTR even in RTL layouts

---

#### `pseudo-loc`

Generate pseudo-localized versions of translations for testing.

- Create a pseudo-locale (e.g., `en-XA` for accented, `ar-XB` for RTL pseudo):
  - **Accented pseudo-locale** (`en-XA`): Replace ASCII characters with accented equivalents (`a` → `ä`, `e` → `ë`, etc.), expand string length by ~30-40% with padding characters (e.g., `[Ħëëëëëĺĺĺĺĺö Ŵööööřĺĺĺĺď]`)
  - **RTL pseudo-locale** (`ar-XB`): Wrap text in RTL override characters to test layout without actual Arabic text
  - **Extra-long pseudo-locale**: Expand strings by 50-100% to stress-test UI overflow and truncation
  - **CJK pseudo-locale**: Replace characters with CJK equivalents to test double-width character handling
- Preserve all ICU placeholders, HTML tags, and interpolation variables - only transform literal text
- Bracket all pseudo-localized strings so missing translations are visually obvious: `[Ħëëĺĺö]` - if a bracket is cut off, the string is being truncated by the UI
- Register pseudo-locale in the i18n config for development mode only
- Warn: "Pseudo-localization is for development/testing only - do not ship to production."

---

#### `namespace`

Manage translation file namespaces and splitting strategies.

**Analyze current structure**:
- Map all translation keys to the source files that reference them
- Identify natural groupings: per page/route, per feature, shared/common
- Calculate file sizes and key counts per namespace
- Detect namespace collisions (same key in multiple namespaces with different values)

**Split large files**:
- Recommend splitting when a single translation file exceeds 500 keys or 50KB
- Suggest namespace boundaries based on route structure:
  ```
  locales/en/common.json     → shared UI strings (buttons, labels, errors)
  locales/en/auth.json       → login, signup, password reset
  locales/en/dashboard.json  → dashboard-specific strings
  locales/en/settings.json   → settings page strings
  locales/en/emails.json     → email template strings
  ```
- Update all source file imports to reference the correct namespace
- Update i18n config to load namespaces

**Lazy loading setup**:
- For React: configure namespace-based code splitting with `react-i18next` `useTranslation('namespace')` or `next-intl` `useMessages()`
- For Vue: configure `vue-i18n` lazy loading with dynamic imports
- Ensure that shared/common namespace is always loaded (not lazy)
- Ensure that route-level namespaces are loaded with the route
- Report estimated bundle size savings from lazy loading

**Shared vs feature namespaces**:
- Identify strings used across 3+ pages → move to `common` namespace
- Identify strings used in only one page → keep in feature namespace
- Flag strings that are in `common` but only used in one place (should be moved to feature)

---

### Step 3: Pluralization Deep Dive

When extracting or validating strings that involve quantities, apply CLDR plural rules specific to each locale.

**CLDR plural categories by language family**:

| Language | Plural forms | Categories |
|---|---|---|
| Arabic (`ar`) | 6 | zero, one, two, few (3-10), many (11-99), other (100+) |
| Russian (`ru`) | 4 | one (1, 21, 31...), few (2-4, 22-24...), many (5-20, 25-30...), other (fractions) |
| Polish (`pl`) | 4 | one (1), few (2-4, 22-24...), many (5-21, 25-31...), other (fractions) |
| Czech (`cs`) | 4 | one (1), few (2-4), many (fractions), other |
| French (`fr`) | 3 | one (0-1), many (large numbers w/ compact notation), other |
| English (`en`) | 2 | one (1), other |
| Japanese (`ja`) | 1 | other (all) |
| Chinese (`zh`) | 1 | other (all) |
| Korean (`ko`) | 1 | other (all) |
| Welsh (`cy`) | 6 | zero, one, two, few, many, other |
| Irish (`ga`) | 5 | one, two, few, many, other |

**Ordinal pluralization** (1st, 2nd, 3rd, 4th...):
- English: one (1st, 21st, 31st), two (2nd, 22nd), few (3rd, 23rd), other (4th, 5th...)
- Many languages have no ordinal distinction - use `other` for all
- ICU syntax: `{position, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}`

**Range pluralization** (e.g., "1-3 items"):
- ICU range syntax varies by library - check framework support
- Fallback: use two separate plural messages with a range connector

When validating, ensure each locale provides all required plural categories. Missing a category causes runtime fallback to `other`, which may be grammatically incorrect.

---

### Step 4: Date, Time, Number, and Unit Localization

Beyond string translation, audit and guide locale-aware formatting for data types.

**Number formatting**:
- Verify use of `Intl.NumberFormat` or equivalent rather than hardcoded formatting
- Decimal separator: `.` (en-US), `,` (de, fr, es, pt-BR), `٫` (ar)
- Thousands separator: `,` (en-US), `.` (de, es), ` ` (fr, ru), none (ja, zh)
- Percentage: `45%` (en), `45 %` (fr, de - note the space)
- Currency: `$1,234.56` (en-US), `1.234,56 €` (de), `￥1,234` (ja), `١٬٢٣٤٫٥٦ ر.س` (ar-SA)
- Currency symbol placement: prefix (en, ja), suffix (de, fr), code (`USD`) for ambiguous contexts
- Compact notation: `1.2K` (en), `1,2 Mrd.` (de), `1.2万` (ja), `1,2 тыс.` (ru)

**Date/time formatting**:
- Verify use of `Intl.DateTimeFormat` or equivalent
- Date order: MDY (en-US), DMY (en-GB, most of Europe), YMD (ja, ko, zh, ISO 8601)
- Month names: long (`January`), short (`Jan`), narrow (`J`) - all must be locale-aware
- 12h vs 24h: US/UK use 12h with AM/PM; most of Europe, Asia use 24h
- First day of week: Sunday (en-US), Monday (en-GB, most of Europe), Saturday (ar, fa)
- Calendar system: Gregorian (default), Hijri (ar-SA), Buddhist (th-TH), Japanese Imperial (ja-JP-u-ca-japanese)
- Relative time: "2 hours ago", "in 3 days" - use `Intl.RelativeTimeFormat`

**Unit formatting**:
- Distance: miles (en-US), kilometers (most of the world)
- Temperature: Fahrenheit (en-US), Celsius (everywhere else)
- Weight: pounds (en-US), kilograms
- Paper size: Letter (en-US), A4 (everywhere else)
- Use `Intl.NumberFormat` with `style: 'unit'` where supported

**Phone number formatting**:
- Always display in locale-appropriate format: `(555) 123-4567` (US), `+44 20 7946 0958` (UK)
- Use a library like `libphonenumber` - do not hardcode format patterns

**Address formatting**:
- Field order varies by country (Japan: postal code, prefecture, city, street; US: street, city, state, zip)
- Flag hardcoded address templates in translations - recommend structured address components

---

### Step 5: Testing i18n

Provide guidance and generate test utilities for i18n correctness.

**Pseudo-localization testing**:
- Generate pseudo-locale files (see `pseudo-loc` action)
- Verify all UI strings are sourced from translation files - any un-pseudo-localized text is a hardcoded string
- Check that bracketed strings `[Ħëĺĺö Ŵöřĺď]` are fully visible (not truncated by CSS `overflow: hidden`, `text-overflow: ellipsis`, or fixed-width containers)
- Test that 30-40% longer strings do not break layouts, overflow buttons, or cause horizontal scrolling

**Missing translation error boundaries**:
- Verify the app has fallback behavior when a translation key is missing:
  - Option A: Fall back to default locale (recommended for production)
  - Option B: Show the key itself (useful for development)
  - Option C: Show an error boundary / visual indicator (useful for QA)
- Check that missing translations are logged/reported in development but do not crash in production
- Test the full fallback chain: requested locale → regional fallback (`pt-BR` → `pt`) → default locale → key itself

**Screenshot testing across locales**:
- Recommend visual regression testing tools: Chromatic, Percy, Playwright screenshots, Storybook
- Key pages to screenshot in all locales: login, main dashboard, settings, forms with validation errors
- RTL locales require their own screenshot baseline - layout is mirrored
- CJK locales may need different line-height and font-size considerations
- German/Finnish (long strings) stress-test layout width constraints

**Automated validation in CI**:
- Suggest adding a CI step that runs `validate` on every PR that touches translation files or source files
- Check for missing translations before deploy - block deploy if coverage drops below threshold
- Validate ICU syntax in CI to catch translator errors early
- Lint for hardcoded strings in source files (flag new strings not wrapped in `t()`)

---

### Step 6: SSR/SSG Considerations

Guide locale handling for server-rendered and statically generated applications.

**Static site generation (SSG) per locale**:
- Next.js App Router: verify `generateStaticParams` yields all locale values
- Next.js Pages Router: verify `getStaticPaths` includes all locales
- Nuxt: verify `nuxt-i18n` `strategy` and `locales` config for static generation
- Astro: verify `i18n` routing config and static locale page generation
- Ensure each locale generates its own set of pages at build time
- Verify that translation files are loaded at build time, not fetched at runtime
- For ISR (Incremental Static Regeneration): verify locale is part of the cache key

**Dynamic locale detection**:
- Server-side: parse `Accept-Language` header, match against supported locales with quality weighting
- Use a proper locale matching algorithm (not just `startsWith`): `Intl.LocaleMatcher` or `@formatjs/intl-localematcher`
- Middleware-based detection (Next.js middleware, Express middleware, Nuxt server middleware)
- Fallback chain: URL → cookie → `Accept-Language` header → default locale
- Verify locale detection does not break caching - locale should be in the URL or vary header

**URL strategy**:

| Strategy | Example | Pros | Cons |
|---|---|---|---|
| Path prefix | `/en/about`, `/fr/about` | SEO-friendly, easy to implement, cacheable | Longer URLs |
| Subdomain | `en.site.com`, `fr.site.com` | Clean URLs, can point to different servers | DNS/cert setup, cookie sharing |
| Query param | `/about?lang=fr` | Simple | Poor SEO, not cacheable by default |
| Cookie/header only | `/about` (same URL) | Clean URLs | Not crawlable, poor SEO, caching issues |

Recommendation: path prefix is the best default for SEO and caching.

**SEO and hreflang**:
- Verify every page includes `<link rel="alternate" hreflang="x" href="..." />` for all available locales
- Include `hreflang="x-default"` pointing to the default locale or a locale selector page
- Verify `<html lang="xx">` attribute is set correctly per locale (and `dir="rtl"` for RTL locales)
- Check `<meta property="og:locale">` and `og:locale:alternate` for social sharing
- Verify canonical URLs are locale-specific: `/en/about` canonical should be `/en/about`, not `/about`

**Sitemap per locale**:
- Verify `sitemap.xml` includes all locale variants of each page
- Each URL entry should include `<xhtml:link rel="alternate" hreflang="..." href="..." />` sub-elements
- Or generate separate sitemaps per locale with a sitemap index
- Verify robots.txt does not block locale-prefixed paths

---

### Step 7: Report

**Template:** `templates/i18n-status-report.md`
Full report template covering framework setup, locale coverage, missing translations, ICU validation, XSS risks, terminology, length warnings, RTL audit, unused keys, hardcoded strings, interpolation mismatches, SEO/SSR status, namespace health, and recommended actions.

---

## Configuration

Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:

**Template:** `templates/config-schema.jsonc`
Complete `_config.json` schema with all supported options: core settings, namespace strategy, validation thresholds, extraction categories, RTL settings, export/import preferences, and SSR/SSG configuration.
