# PostgreSQL: Create a backup and verify it
pg_dump -Fc production_db > pre_migration_backup.dump
pg_restore --list pre_migration_backup.dump > /dev/null && echo "Backup valid"

# Verify backup by restoring to a test database
createdb restore_test
pg_restore -d restore_test pre_migration_backup.dump
psql restore_test -c "SELECT count(*) FROM users;"  # Sanity check
dropdb restore_test

# MySQL: backup and verify
mysqldump --single-transaction production_db > pre_migration_backup.sql
mysql -e "CREATE DATABASE restore_test; USE restore_test; SOURCE pre_migration_backup.sql;"
mysql -e "SELECT count(*) FROM restore_test.users;"
mysql -e "DROP DATABASE restore_test;"
