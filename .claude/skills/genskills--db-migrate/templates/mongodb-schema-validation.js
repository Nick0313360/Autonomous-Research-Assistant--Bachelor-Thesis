// Add schema validation to existing collection
db.runCommand({
  collMod: "users",
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["email", "createdAt"],
      properties: {
        email: { bsonType: "string", pattern: "^.+@.+\\..+$" },
        role: { enum: ["admin", "user", "viewer"] },
        createdAt: { bsonType: "date" }
      }
    }
  },
  validationLevel: "moderate",  // Only validates inserts and updates to matching docs
  validationAction: "warn"      // Start with warn, switch to error once backfill is done
});

// Backfill missing fields to pass strict validation
db.users.updateMany(
  { createdAt: { $exists: false } },
  { $set: { createdAt: new Date() } }
);

// Then tighten validation
db.runCommand({
  collMod: "users",
  validationLevel: "strict",
  validationAction: "error"
});
