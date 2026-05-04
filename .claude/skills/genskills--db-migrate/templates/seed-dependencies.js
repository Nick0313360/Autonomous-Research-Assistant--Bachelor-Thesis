// 001_roles.ts - no dependencies
exports.run = async (knex) => {
  await knex('roles').insert([
    { id: 1, name: 'admin' },
    { id: 2, name: 'user' },
  ]).onConflict('id').ignore();
};

// 002_users.ts - depends on 001_roles
exports.dependencies = ['001_roles'];
exports.run = async (knex) => {
  await knex('users').insert([
    { id: 1, email: 'admin@example.com', role_id: 1 },
  ]).onConflict('id').ignore();
};
