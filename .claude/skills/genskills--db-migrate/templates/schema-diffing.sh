# PostgreSQL
pg_dump --schema-only mydb > before.sql
# ... run migration ...
pg_dump --schema-only mydb > after.sql
diff before.sql after.sql

# MySQL
mysqldump --no-data mydb > before.sql
# ... run migration ...
mysqldump --no-data mydb > after.sql
diff before.sql after.sql

# Prisma-specific
npx prisma migrate diff --from-schema-datasource prisma/schema.prisma --to-migrations prisma/migrations
