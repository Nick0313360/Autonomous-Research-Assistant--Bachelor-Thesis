# PostgreSQL with WAL archiving
# 1. Stop the application
# 2. Identify the timestamp just before the migration ran
# 3. Restore from base backup + WAL replay
pg_restore -d recovery_db base_backup.dump
# Configure recovery.conf / postgresql.conf:
#   recovery_target_time = '2025-03-25 14:30:00 UTC'
#   recovery_target_action = 'pause'
# 4. Start PostgreSQL - it replays WAL up to the target time
# 5. Verify the data state
# 6. Promote from recovery and switch application to recovered database

# MySQL with binary logs
mysqlbinlog --stop-datetime="2025-03-25 14:30:00" binlog.000042 | mysql -u root recovery_db
