# Extract-Transform-Load pattern
def migrate_users():
    # Extract: read from old schema/system
    old_users = old_db.execute("SELECT * FROM legacy_users")

    # Transform: map to new shape
    new_users = []
    for user in old_users:
        new_users.append({
            'id': user['user_id'],
            'full_name': f"{user['first_name']} {user['last_name']}",
            'email': user['email'].lower().strip(),
            'created_at': parse_legacy_date(user['create_date']),
            'role': map_legacy_role(user['user_type']),
        })

    # Load: write to new schema/system
    for batch in chunk(new_users, size=1000):
        new_db.execute(
            insert(User).values(batch)
        )

    # Validate
    old_count = old_db.execute("SELECT COUNT(*) FROM legacy_users").scalar()
    new_count = new_db.execute("SELECT COUNT(*) FROM users").scalar()
    assert old_count == new_count, f"Count mismatch: {old_count} vs {new_count}"
