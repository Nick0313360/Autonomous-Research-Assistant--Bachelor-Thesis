# Example: Migrate from flat keys to hash structure
import redis

r = redis.Redis()
cursor = 0
batch_size = 1000
migrated = 0

while True:
    cursor, keys = r.scan(cursor, match="user:*:email", count=batch_size)
    pipe = r.pipeline()
    for key in keys:
        # Old format: user:123:email = "foo@bar.com"
        # New format: user:123 = {email: "foo@bar.com", ...}
        user_id = key.decode().split(":")[1]
        email = r.get(key)
        pipe.hset(f"user:{user_id}", "email", email)
        pipe.delete(key)
    pipe.execute()
    migrated += len(keys)
    print(f"Migrated {migrated} keys")
    if cursor == 0:
        break
