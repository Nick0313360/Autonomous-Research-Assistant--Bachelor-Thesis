---
name: genskills:mock-data
description: >
  Generate realistic mock/seed data for databases, APIs, and tests.
  Triggers on: "mock data", "seed data", "fake data", "generate fixtures",
  "test data", "sample data".
user-invocable: true
argument-hint: "[model/schema] [count] - e.g., 'User 50' or 'seed all'"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(npm *), Bash(npx *), Bash(python *), Bash(node *)"
genskills-version: "1.4.2"
genskills-category: "development"
genskills-depends: []
---

# Mock Data

Generate realistic, consistent, and statistically plausible mock and seed data for any environment - development, testing, staging, or demo.

## Process

### Step 0: Load Context
- Check `CLAUDE.md` for data conventions, naming patterns, and domain requirements
- Check `${CLAUDE_SKILL_DIR}/_config.json` for preferences
- Identify the project domain (e-commerce, healthcare, fintech, social media, SaaS, etc.) to select appropriate data patterns
- Detect existing seed files, factories, or fixtures to avoid duplication and maintain consistency

### Step 1: Detect Data Models
Parse `$ARGUMENTS`:
- `$0` = model name, "all", "seed", or "anonymize"
- `$1` = count (default: 10)
- `--format` = output format: `json`, `csv`, `sql`, `ts`, `py`, `prisma-seed`, `factory`, `msw`, `graphql`
- `--env` = target environment: `development`, `staging`, `demo`, `testing` (default: `development`)
- `--distribution` = statistical profile: `realistic`, `uniform`, `edge-cases` (default: `realistic`)
- `--seed` = deterministic seed number for reproducible output
- `--batch-size` = records per insert batch for large datasets (default: 1000)
- `--stream` = enable streaming generation for datasets exceeding 10,000 records
- `--anonymize-from` = path to real schema/data to anonymize rather than generate from scratch

Auto-detect models from:
- Prisma schema (`schema.prisma`)
- TypeORM / Sequelize / Drizzle models
- Django / SQLAlchemy models
- TypeScript interfaces/types in `models/` or `types/`
- GraphQL schema types
- Zod / Yup / Joi validation schemas
- JSON Schema definitions
- OpenAPI / Swagger specs (extract request/response models)
- Mongoose / MongoDB schemas
- Protobuf message definitions

### Step 2: Analyze Model Fields
For each model, map fields to appropriate generators:

| Field Pattern | Generator | Distribution / Notes |
|---|---|---|
| `id` | UUID v4 or auto-increment | Sequential or random based on ORM convention |
| `email` | Realistic email (faker) | Unique constraint enforced; domain variety |
| `name`, `firstName`, `lastName` | Person names | Locale-aware; culturally diverse mix |
| `phone` | Phone numbers | E.164 format; region-appropriate |
| `avatar`, `image`, `photo` | Placeholder image URLs | Deterministic URLs (e.g., `i.pravatar.cc/150?u=<id>`) |
| `address`, `street`, `city`, `zip` | Address components | Internally consistent (city matches zip matches state) |
| `price`, `amount`, `cost` | Currency values (2 decimal) | Log-normal distribution; realistic price points |
| `createdAt`, `updatedAt` | Dates with temporal consistency | `updatedAt >= createdAt`; realistic gaps |
| `deletedAt` | Soft-delete timestamp or null | Null for ~90% of records; always `>= updatedAt` |
| `status` | From enum values | Weighted by realistic state distribution (see state machines below) |
| `description`, `bio`, `content` | Lorem/realistic text | Varied lengths; occasional emoji and Unicode |
| `slug` | Kebab-case from name field | Unique; derived from related text field |
| `url`, `website` | Valid URLs | Mix of HTTP/HTTPS; realistic TLDs |
| `lat`, `lng`, `latitude`, `longitude` | Geo coordinates | Within valid ranges; clustered around real cities |
| `password`, `hash` | Bcrypt hash placeholder | Always use `$2b$10$...` placeholder; never real passwords |
| `boolean` fields (`isActive`, `verified`) | Weighted random | ~80% active, ~60% verified (configurable) |
| `rating`, `score` | Numeric ratings | J-shaped distribution (most ratings 4-5 stars) |
| `count`, `views`, `likes` | Engagement metrics | Zipf/power-law distribution |
| `age` | Integer age | Normal distribution, mean ~35, stddev ~15, clamped 18-90 |
| `salary`, `revenue` | Financial amounts | Log-normal distribution |
| `tags`, `categories` | Array of strings | 1-5 items from realistic pool; follows Zipf for tag popularity |
| `json`, `metadata`, `config` | Structured JSON | Realistic nested objects matching field semantics |
| `ip`, `ipAddress` | IPv4/IPv6 addresses | Private ranges for dev; realistic distribution |
| `userAgent` | Browser user-agent strings | Weighted by real-world browser market share |

### Step 3: Domain-Specific Data Patterns

Detect the project domain and apply specialized generators:

**E-Commerce:**
- Product SKUs: formatted as `CAT-BRAND-12345` with category prefixes
- Shipping addresses: complete and internally consistent (street, city, state, zip, country)
- Order statuses: weighted distribution (70% delivered, 15% shipped, 10% processing, 5% cancelled)
- Order totals: sum of line items plus tax and shipping (mathematically consistent)
- Product reviews: correlated with purchase history (reviewers must have purchased)
- Inventory counts: integer, normally distributed around category-specific means
- Discount codes: realistic format, some expired, some usage-limited
- Payment methods: mix of card types with masked numbers (`**** **** **** 4242`)

**Healthcare:**
- ICD-10 codes: valid format (e.g., `J06.9`, `E11.65`) from common diagnosis pools
- Patient records: HIPAA placeholder data clearly marked as synthetic (`[SYNTHETIC]` prefix)
- Appointment slots: during business hours, 15/30/60 minute durations, no double-booking
- Medication records: realistic drug names, dosages, frequencies from common formulary
- Lab results: values within plausible ranges with appropriate units
- Insurance IDs: valid format patterns without real payer data
- Provider NPIs: 10-digit format with valid check digit algorithm

**Fintech / Banking:**
- IBAN numbers: valid format with correct country prefix and check digits
- Transaction histories: chronologically ordered, balanced debits/credits, running balances
- Currency pairs: real ISO 4217 codes (USD, EUR, GBP, JPY) with realistic exchange rates
- Account numbers: format-valid but clearly synthetic (test range prefixes)
- Transaction categories: MCC codes with descriptions
- KYC status fields: valid state transitions (pending -> verified -> approved)
- Interest calculations: mathematically consistent with principal and rate

**Social Media:**
- Engagement metrics: views >> likes >> comments >> shares (funnel ratios ~100:10:3:1)
- Content moderation flags: realistic flag types (spam, harassment, misinformation) with review states
- Follower/following counts: power-law distribution (most users have few, few have many)
- Post timestamps: clustered around peak hours (9-11am, 7-9pm) with timezone awareness
- Hashtags: Zipf-distributed popularity; trending tags on recent posts
- User verification status: rare (~2% of users)
- Content types: weighted mix (60% text, 25% image, 10% video, 5% link)

**SaaS / Multi-tenant:**
- Organization hierarchies: realistic tree depth (2-4 levels)
- Subscription tiers: weighted (60% free, 25% pro, 12% business, 3% enterprise)
- Feature flags: per-tenant overrides with inheritance
- API keys: prefixed format (`sk_live_...`, `sk_test_...`) clearly marked as test keys
- Usage metrics: correlated with subscription tier
- Audit logs: chronological with actor, action, resource, timestamp

### Step 4: Statistical Distributions

Apply realistic statistical distributions rather than uniform random:

**Normal Distribution:**
- Human ages: `N(35, 15)` clamped to valid range
- Product ratings: `N(4.2, 0.8)` clamped to 1-5
- Response times: `N(250, 100)` ms for API latency data
- Employee salaries: within band ranges per role/level

**Zipf / Power-Law Distribution:**
- Content popularity (views, likes): most content gets little engagement, few go viral
- Tag/category frequency: a few tags dominate, long tail of rare ones
- User activity levels: most users are lurkers, few are power users
- City population in addresses: more records from larger cities
- Search query frequency: head terms vs. long tail

**Exponential Distribution:**
- Time between events (inter-arrival times for logs, orders, signups)
- Session durations: most short, exponentially fewer long sessions
- Support ticket resolution times: skewed toward quick resolutions

**Seasonal / Time-Series Patterns:**
- E-commerce orders peak during holiday seasons and weekends
- SaaS signups show day-of-week patterns (higher Mon-Thu)
- Social media posts cluster around meal times and evening hours
- Support tickets spike after product releases
- Revenue shows monthly/quarterly growth patterns

**Realistic Growth Curves:**
- User signups: S-curve (slow start, exponential growth, plateau)
- Revenue: hockey-stick or linear growth depending on stage
- Content volume: exponential growth with user base

### Step 5: Temporal Consistency

All time-based data must obey strict temporal rules:

**Timestamp Ordering:**
- `createdAt` <= `updatedAt` <= `deletedAt` (when soft-deleted)
- `startDate` <= `endDate` for date ranges
- `orderedAt` <= `shippedAt` <= `deliveredAt` for order lifecycle
- `invitedAt` <= `acceptedAt` <= `lastLoginAt` for user lifecycle
- Event sequences respect causality (no effect before cause)

**State Machine Transitions:**
Generate status histories that follow valid transition paths:

**Template:** `templates/state-machine-transitions.txt`
Valid status transition paths for Order, User, Content, Ticket, and Subscription entities.

- Current status distribution is weighted realistically (most orders delivered, most users active)
- Status history timestamps are monotonically increasing with realistic gaps
- Intermediate states have plausible durations (shipping takes 1-7 days, not 1 second)

**Timezone Awareness:**
- Login timestamps during reasonable hours (7am-1am) in the user's configured timezone
- Business events during business hours in the company's timezone
- Global datasets show activity following the sun (peak usage rotates through timezones)
- Handle DST transitions: no timestamps in the skipped hour, duplicates possible in the repeated hour
- Store all timestamps in UTC with timezone metadata where the schema supports it

**Calendar Edge Cases:**
- Include Feb 29 dates in leap years when generating date ranges spanning leap years
- Month-end dates (28th, 29th, 30th, 31st) distributed correctly
- No invalid dates like Apr 31, Jun 31, Feb 30

### Step 6: Graph and Relationship Complexity

**Social Graphs (Follow/Friend Relationships):**
- Realistic clustering coefficient: friend-of-friend connections are common
- Power-law degree distribution: most users have 10-100 connections, influencers have 10k+
- Reciprocity rate: ~60% of follows are mutual in friend-based networks
- Community structure: identifiable clusters (friend groups, interest groups)
- No self-follows; enforce unique (follower, following) pairs

**Organizational Hierarchies:**
- Tree structures with realistic depth (CEO -> VP -> Director -> Manager -> IC)
- Span of control: 3-8 direct reports per manager
- Single root node (no orphaned branches)
- Every non-root node has exactly one parent
- Department grouping within hierarchy levels

**Product Category Trees (DAG Structures):**
- Categories form a directed acyclic graph (products can be in multiple categories)
- Depth typically 2-4 levels (Electronics -> Phones -> Smartphones -> Android)
- Leaf categories contain products; intermediate categories are organizational
- Breadcrumb paths are consistent

**Comment Threads (Nested Replies):**
- Tree structure with configurable max depth (typically 5-10 levels)
- Reply depth follows exponential decay (most replies are top-level)
- Thread participation: original poster often replies in thread
- Timestamps within thread are chronologically ordered
- Deleted comments: `[deleted]` placeholder with children preserved

**Polymorphic Associations:**
- `commentable_type` + `commentable_id` patterns with valid type/ID combinations
- `attachable`, `taggable`, `likeable` polymorphic patterns
- Ensure referenced records actually exist in the target table
- Type distribution weighted by domain logic

**Many-to-Many with Metadata:**
- Junction tables with additional fields (e.g., `role` in `project_members`, `quantity` in `order_items`)
- Avoid exact duplicate join records
- Realistic cardinality (users belong to 1-5 projects, projects have 2-20 members)

### Step 7: Edge Case Data Generation

Generate data that specifically tests boundary conditions:

**Unicode and Encoding:**
- Names with accented characters: `Renee`, `Muller`, `Joao`, `Bjork`
- CJK characters in text fields: product names, addresses in Asian markets
- Emoji in user-generated content: bios, comments, product reviews
- RTL text samples for internationalized fields (Arabic, Hebrew)
- Zero-width characters and combining marks
- Multi-byte characters at string boundaries

**Boundary Values:**
- Empty strings (`""`) at configured null rate (~5% of optional text fields)
- Maximum-length strings hitting VARCHAR limits (255, 1000, 65535 chars)
- Numeric boundaries: `0`, `-1`, `MAX_INT`, `MIN_INT`, `0.01`, `999999.99`
- Empty arrays for array/JSON fields
- Deeply nested JSON (5+ levels) for JSON column stress testing

**Special Characters:**
- Strings containing single quotes, double quotes, backticks: `O'Brien`, `She said "hello"`
- Backslashes and escape sequences: `C:\Users\test`, `line1\nline2`
- SQL-safe test strings: `'; DROP TABLE users; --` (safe because data is fake, but tests escaping)
- XSS test vectors in text fields: `<script>alert('xss')</script>`, `<img onerror=alert(1)>`
- Strings with leading/trailing whitespace
- Null bytes and control characters (at low rates, clearly flagged)
- Ampersands, angle brackets, and other XML/HTML special characters

**Date/Time Edge Cases:**
- Dates around DST transitions (spring forward / fall back)
- Leap year dates: `2024-02-29`
- Year boundaries: `2023-12-31T23:59:59Z` -> `2024-01-01T00:00:00Z`
- Epoch-adjacent dates: `1970-01-01`, `2038-01-19` (Y2038 boundary)
- Far-future dates for expiration fields: `2099-12-31`
- Timezone extremes: `UTC+14`, `UTC-12`

**Numeric Edge Cases:**
- Floating-point precision: `0.1 + 0.2` scenarios in financial calculations
- Very large counts for stress testing aggregation queries
- Negative values where sign matters (refunds, adjustments, temperature)
- Currency amounts with various decimal conventions (JPY has 0 decimals, BHD has 3)

### Step 8: Performance-Scale Data Generation

For datasets exceeding 10,000 records, use memory-efficient strategies:

**Streaming Generation:**
```typescript
// Generate records as an async iterable - never hold all in memory
async function* generateUsers(count: number): AsyncGenerator<User> {
  for (let i = 0; i < count; i++) {
    yield createUser(i);
    // Yield control periodically to avoid blocking
    if (i % 1000 === 0) await new Promise(r => setImmediate(r));
  }
}
```

**Chunked Database Inserts:**
- Batch size optimization: 500-2000 records per INSERT (profile and adjust)
- Transaction wrapping per chunk (not one giant transaction)
- Disable indexes before bulk insert, rebuild after (for 100k+ records)
- Use COPY/bulk insert APIs when available (Postgres COPY, MySQL LOAD DATA)
- Progress reporting: log every 10,000 records with elapsed time and ETA

**Parallel Generation for Independent Tables:**
- Tables without foreign key dependencies can be generated concurrently
- Build a dependency graph and generate in topological order
- Leaf tables (no outgoing FKs) can all run in parallel
- Coordinate ID ranges to avoid conflicts in parallel generation

**Memory Budgeting:**
- For 1M+ records: stream directly to file or database, never buffer in memory
- Maintain only a window of recent IDs for foreign key references
- Use deterministic ID generation (seeded PRNG) so related records can reference IDs without lookup
- Report estimated memory usage before starting large generations

**Benchmarks to Target:**
- 10k records: < 2 seconds, in-memory is fine
- 100k records: < 30 seconds, chunked inserts
- 1M records: < 5 minutes, streaming + parallel + bulk APIs
- 10M+ records: warn user, suggest database-native generation tools

### Step 9: Environment-Specific Seed Profiles

Generate different data profiles based on the target environment:

**Development (`--env development`):**
- Small dataset: 10-50 records per model
- Fast generation: < 5 seconds total
- Covers all UI states: at least one record in every possible status
- Includes one "admin" user with known credentials (`admin@example.com` / `password123`)
- One record per enum value to exercise all code paths
- Deterministic by default (same seed every run for predictable local dev)
- Includes visual variety (different avatars, varied content lengths)

**Staging (`--env staging`):**
- Production-scale subset: 1,000-10,000 records per major model
- Anonymized patterns: realistic but clearly synthetic
- Performance-representative: enough data to surface N+1 queries and slow pagination
- Includes realistic data skew (some users with many orders, most with few)
- Multi-tenant data if applicable (3-5 organizations with varying sizes)
- Load test preparation: enough data for meaningful benchmarks

**Demo (`--env demo`):**
- Curated showcase data with realistic narratives
- Named personas: "Acme Corp", "Jane Smith (Power User)", "New Startup (Trial)"
- Visually appealing: real-looking product images, professional bios
- Showcases all premium features with compelling examples
- Tells a story: demo user has realistic activity history showing product value
- Company names and branding that look professional in screenshots
- Conversation threads and interactions that read naturally

**Testing (`--env testing`):**
- Minimal: only what each test suite needs
- Deterministic: identical output for given seed number (reproducible failures)
- Edge case coverage: every boundary condition represented
- Isolated: each test file gets independent fixtures (no shared mutable state)
- Fast: generated at test setup time with factory functions, not file I/O
- Includes deliberately invalid data for negative test cases (in separate fixtures)

### Step 10: MSW / API Mock Server Generation

Generate Mock Service Worker (MSW) handlers and API mock infrastructure:

**MSW Handler Generation:**

**Template:** `templates/msw-handlers.ts`
MSW request handlers for paginated list, single resource, and create endpoints with realistic delays and validation errors.

**Error Simulation Handlers:**

**Template:** `templates/msw-error-handlers.ts`
MSW overlay handlers for testing rate limiting (429), intermittent server errors (500), and slow responses (timeout scenarios).

**Pagination Simulation:**
- Cursor-based: generate stable cursors encoding position, return `hasNextPage` / `endCursor`
- Offset-based: consistent total count, correct slice for any page/limit combo
- Keyset-based: ordered by creation date with stable ordering

**WebSocket Mock Events:**

**Template:** `templates/msw-websocket-handlers.ts`
MSW WebSocket handler simulating periodic notification events with connection lifecycle management.

**GraphQL Mock Resolvers:**
- Generate resolvers matching schema types with realistic pagination (Relay connections)
- Support for query variables (filtering, sorting)
- Simulate loading states and partial errors

### Step 11: Data Anonymization

Generate production-like data from real schemas without exposing PII:

**Consistent Anonymization (Deterministic Mapping):**
- Same real input always maps to the same fake output (hash-based mapping)
- Preserves referential integrity: if user `alice@real.com` becomes `user_7f3a@example.com`, it does so everywhere
- Use HMAC with a secret key for the mapping function (key never stored in generated output)

**Preserve Statistical Properties:**
- Maintain data distributions: if 30% of real users are from California, 30% of fake users should be too
- Preserve cardinality: if a real user has 47 orders, their anonymized counterpart has 47 orders
- Maintain temporal patterns: preserve day-of-week and hour-of-day distributions
- Keep numeric ranges realistic: anonymized salaries stay within the same bands

**Field-Level Strategies:**
| Field Type | Anonymization Strategy |
|---|---|
| Email | `hash(email)@example.com` - deterministic, unique |
| Full name | Map to faker name with consistent seed from original |
| Phone | Preserve country code, randomize remaining digits |
| Address | Map to different real address in same postal region |
| Date of birth | Shift by random fixed offset (preserving age bracket) |
| SSN / National ID | Replace with valid-format synthetic number |
| Free text | Replace PII tokens with placeholders, preserve structure |
| IP address | Map to same /16 subnet, randomize host portion |
| GPS coordinates | Add noise within 1km radius (preserves neighborhood-level analysis) |
| Financial amounts | Multiply by consistent random factor (0.8-1.2) |

**GDPR-Compliant Test Data Strategies:**
- Never copy production data to lower environments - generate synthetic data that matches the schema
- When production analysis is needed, anonymize at the query layer (views) rather than copying
- Maintain an anonymization manifest documenting which fields are modified and how
- Provide a `--verify-anonymization` flag that scans output for patterns matching real PII formats
- Include synthetic data provenance headers/comments: `/* SYNTHETIC DATA - DO NOT TREAT AS REAL */`

### Step 12: Snapshot and Fixture Management

**Version-Controlled Fixtures:**
- Store fixtures in `__fixtures__/` or `tests/fixtures/` (match project convention)
- Use diff-friendly JSON formatting: sorted keys, 2-space indent, one array element per line
- Include a `_meta` field with generation timestamp and seed number for reproducibility

**Template:** `templates/fixture-metadata.json`
Example JSON fixture with `_meta` generation metadata (timestamp, seed, generator version).

**Fixture Inheritance (Base + Overrides):**

**Template:** `templates/fixture-inheritance.ts`
Base user fixture with override patterns for admin, Unicode, max-length, and new user edge cases.

**Shared Fixtures Across Test Suites:**
- Central fixture registry that multiple test files import from
- Each fixture set is immutable - tests must deep-clone if they mutate
- Lazy generation: fixtures created on first access, cached for the test run
- Fixture dependencies automatically resolved (user fixtures load before order fixtures)
- Cleanup utilities: `resetFixtures()` for test isolation

**Snapshot Diffing:**
- When regenerating fixtures, show a diff summary: "Changed 3 users, added 2 products, removed 1 category"
- Warn if regeneration would break existing snapshot tests
- Support `--update-snapshots` flag to regenerate and update all dependent fixtures

### Step 13: Handle Relationships
- **One-to-many**: Generate parent records first, assign valid foreign keys to children
- **Many-to-many**: Generate junction table records linking existing IDs with metadata
- **Self-referencing**: Generate tree structures with null roots and bounded depth
- **Polymorphic**: Generate valid type/ID pairs referencing existing records
- **Composite keys**: Generate unique combinations for compound primary/unique keys
- Maintain referential integrity across all generated data
- Respect unique constraints - no duplicate emails, usernames, slugs, etc.
- Respect check constraints - positive prices, valid percentage ranges, etc.
- Foreign key ordering: topological sort of table dependency graph for insert order

### Step 14: Generate Data

**Prisma Seed** (`prisma/seed.ts`):

**Template:** `templates/prisma-seed.ts`
Complete Prisma seed script with deterministic faker, transaction-based cleanup, and weighted role distribution.

**Factory Pattern** (for tests):

**Template:** `templates/factory-pattern.ts`
User factory with sequential IDs, override support, convenience builders (admin, inactive), and batch generation with relationships.

**JSON Fixtures** (`fixtures/<model>.json`):
- Array of N records with realistic data
- Sorted keys for diff-friendly version control
- Includes `_meta` generation metadata

**SQL Seed** (`seed.sql`):
- INSERT statements in topological dependency order
- Wrapped in transaction with rollback on error
- Chunked into batches of 1000 for large datasets
- Includes FK constraint disable/enable for bulk loading

**CSV Export** (`seed/<model>.csv`):
- Header row matching column names
- Proper escaping for commas, quotes, newlines in values
- UTF-8 BOM for Excel compatibility when needed

### Step 15: Wire Up
- If Prisma: add seed script to `package.json` (`"prisma": { "seed": "ts-node prisma/seed.ts" }`)
- If factories: export from barrel file (`factories/index.ts`)
- If fixtures: create loader utility with caching and cleanup
- If MSW: set up `mocks/browser.ts` and `mocks/server.ts` entry points
- If environment-specific: add npm scripts (`seed:dev`, `seed:staging`, `seed:demo`)
- Add `.gitkeep` or documentation to fixture directories
- Update `.env.example` with any seed-specific environment variables

### Step 16: Report

**Template:** `templates/generation-report.md`
Summary report template covering models generated, statistical properties, files created, usage commands, edge cases, and notes.

## Configuration
- `defaultCount`: number - default records per model (default: 10)
- `locale`: string - faker locale for names/addresses (default: "en")
- `locales`: string[] - multiple locales for international datasets (default: ["en"])
- `outputFormat`: string - default format (default: auto-detect)
- `deterministicSeed`: number - faker seed for reproducible data (default: random)
- `nullRate`: number - probability of null for optional fields (default: 0.05)
- `edgeCaseRate`: number - probability of edge case values (default: 0.02)
- `unicodeRate`: number - probability of Unicode/emoji in text fields (default: 0.05)
- `batchSize`: number - records per database insert batch (default: 1000)
- `defaultEnv`: string - default environment profile (default: "development")
- `mswEnabled`: boolean - generate MSW handlers alongside data (default: false)
- `anonymizationKey`: string - HMAC key for deterministic anonymization (default: random)
- `fixtureDir`: string - directory for JSON fixtures (default: auto-detect)
- `diffFriendly`: boolean - sort JSON keys and format for VCS (default: true)
- `maxRelationshipDepth`: number - max depth for nested/recursive relationships (default: 5)
- `realisticDistributions`: boolean - use statistical distributions vs uniform random (default: true)
- `domainPreset`: string - domain-specific preset to load (default: auto-detect from models)
