// Knex example
exports.down = async function(knex) {
  throw new Error(
    'This migration is irreversible. ' +
    'Data transformation from dollars to cents cannot be automatically reversed. ' +
    'Restore from backup if rollback is needed.'
  );
};
