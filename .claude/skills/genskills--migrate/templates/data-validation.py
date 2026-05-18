def validate_migration():
    checks = {
        'row_count': (
            old_db.execute("SELECT COUNT(*) FROM legacy_users").scalar(),
            new_db.execute("SELECT COUNT(*) FROM users").scalar(),
        ),
        'null_emails': (
            0,
            new_db.execute("SELECT COUNT(*) FROM users WHERE email IS NULL").scalar(),
        ),
        'duplicate_emails': (
            0,
            new_db.execute("""
                SELECT COUNT(*) FROM (
                    SELECT email, COUNT(*) c FROM users GROUP BY email HAVING c > 1
                ) t
            """).scalar(),
        ),
        'date_range': (
            True,
            new_db.execute(
                "SELECT MIN(created_at) >= '2000-01-01' AND MAX(created_at) <= NOW() FROM users"
            ).scalar(),
        ),
    }

    for check_name, (expected, actual) in checks.items():
        status = 'PASS' if expected == actual else 'FAIL'
        print(f"  {status}: {check_name} - expected {expected}, got {actual}")
