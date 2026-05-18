# Prisma: detect drift (compares database schema to migration history)
npx prisma migrate diff \
  --from-migrations prisma/migrations \
  --to-schema-datasource prisma/schema.prisma

# Or check for drift status
npx prisma migrate status

# Django: detect unapplied migrations and model-vs-database differences
python manage.py showmigrations
python manage.py migrate --check  # Exit code 1 if unapplied migrations exist
