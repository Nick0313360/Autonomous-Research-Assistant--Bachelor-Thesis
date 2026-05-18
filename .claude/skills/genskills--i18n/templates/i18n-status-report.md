## i18n Status

### Framework & Setup
- Framework: next-intl (Next.js App Router)
- Translation format: JSON (namespaced)
- ICU MessageFormat: Yes
- URL strategy: Path prefix (/en, /fr, /ar)
- Rendering: SSG with ISR

### Locales
- Default: en
- Available: en, es, fr, de, ar (RTL), ja (+ newly added if applicable)
- Total keys: N per locale

### Translation Coverage
| Locale | Translated | Missing | Untranslated | Coverage |
|--------|-----------|---------|--------------|----------|
| en     | 450       | 0       | 0            | 100%     |
| es     | 438       | 12      | 0            | 97.3%    |
| fr     | 447       | 3       | 0            | 99.3%    |
| de     | 450       | 0       | 5 (identical to en) | 98.9% |
| ar     | 430       | 20      | 0            | 95.6%    |
| ja     | 440       | 10      | 0            | 97.8%    |

### Missing Translations
- es: 12 missing keys
  - auth.login.title, auth.signup.subtitle, auth.forgot_password.description, ...
- ar: 20 missing keys
  - dashboard.analytics.*, settings.notifications.*, ...

### ICU Validation Issues
- key "items.count" in `ar` locale: missing required plural categories (zero, two, few, many)
- key "greeting" in `es` locale: ICU syntax error - unbalanced braces
- key "order.status" in `de` locale: missing {orderNumber} placeholder

### HTML/XSS Risks
- key "help.instructions" in `es` locale: contains <script> tag - CRITICAL
- key "welcome.message" in `fr` locale: contains onclick handler - CRITICAL

### Terminology Inconsistencies
- "Dashboard" translated as both "Tableau de bord" and "Panneau" in fr locale
- Brand name "Acme Corp" incorrectly translated in ja locale

### Length Warnings
- de: 15 keys exceed 130% of English length (expected) - verify UI fit
- de: key "settings.privacy.long_description" is 280% of English - likely causes overflow

### RTL Audit (if applicable)
- 23 CSS rules use physical properties (margin-left, padding-right, etc.)
- 5 directional icons found without RTL mirroring
- dir="rtl" attribute: properly configured

### Unused Keys (safe to remove)
- common.old_feature_label - no references in code
- legacy.deprecated_message - no references in code

### Hardcoded Strings Found
- [file:line] "Welcome back" → suggested key: dashboard.welcome_back
- [file:line] "Submit" → suggested key: common.submit
- [file:line] "{count} items in your cart" → suggested key: cart.item_count (ICU plural)
- [file:line] aria-label="Close dialog" → suggested key: a11y.close_dialog

### Interpolation Mismatches
- key "greeting" uses {name} in en but missing in es
- key "order.summary" uses {count} in en but {amount} in fr (variable renamed)

### SEO/SSR
- hreflang tags: present on all pages
- Sitemap: includes all 6 locales
- Missing og:locale:alternate for ar and ja

### Namespace Health
- common.json: 120 keys (OK)
- dashboard.json: 85 keys (OK)
- auth.json: 45 keys (OK)
- legacy.json: 200 keys - consider splitting

### Summary
- Total keys: 450
- Fully translated locales: 1/6 (en)
- Locales above 95%: 5/6
- Hardcoded strings found: N
- ICU issues: N
- XSS risks: N (CRITICAL)
- RTL issues: N

### Recommended Actions
1. [CRITICAL] Fix XSS risks in es and fr translations immediately
2. Fix ICU syntax errors and missing plural categories
3. Send missing keys to translators - export with: /genskills:i18n export xliff
4. Run RTL audit: /genskills:i18n audit-rtl
5. Add pseudo-localization to dev workflow: /genskills:i18n pseudo-loc
6. Add i18n validation to CI pipeline
7. Run /genskills:accessibility-audit to check translated content for a11y
