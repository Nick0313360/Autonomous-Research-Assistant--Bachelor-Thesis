## Mock Data Generated

### Models
- User: 50 records (5 admin, 8 moderator, 37 member)
- Post: 200 records (Zipf-distributed across authors)
- Comment: 500 records (threaded, max depth 5)
- Order: 150 records (105 delivered, 22 shipped, 15 processing, 8 cancelled)

### Statistical Properties
- User ages: N(35, 15), range 18-78
- Post views: Zipf distribution, median 45, max 12,847
- Order values: log-normal, median $47.50, range $3.99-$892.00

### Files Created
- prisma/seed.ts - database seeder (deterministic, seed=42)
- tests/factories/index.ts - factory barrel export
- tests/factories/user.factory.ts - user factory with builders
- tests/factories/post.factory.ts - post factory with relationship support
- fixtures/users.json - JSON fixtures (diff-friendly formatting)
- mocks/handlers.ts - MSW request handlers
- mocks/server.ts - MSW server setup for tests

### Usage
$ npx prisma db seed                 # Seed database (development)
$ npm run seed:staging               # Staging-scale data
$ npm run seed:demo                  # Curated demo data
$ npm test                           # Factories available in all tests

### Temporal Consistency
- All createdAt <= updatedAt verified
- Order status transitions follow valid state machine
- Login timestamps within reasonable hours per user timezone

### Edge Cases Included
- 3 users with Unicode names (accents, CJK)
- 1 user with max-length name (255 chars)
- 5% null values in optional fields
- XSS test strings in 2 comment records
- Leap year dates in date range fields

### Notes
- All relationships maintain referential integrity
- Emails and usernames are unique across the dataset
- Passwords use bcrypt placeholder hash - replace for production seeds
- PII fields use clearly synthetic data (no real personal information)
- Regenerate with: `npx genskills mock-data all 50 --seed 42`
