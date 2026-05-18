// fixtures/base.ts - shared foundation
export const baseUser = {
  role: 'member',
  isActive: true,
  emailVerified: true,
  preferences: { theme: 'system', notifications: true },
};

// fixtures/admin.ts - inherits base, overrides role
export const adminUser = { ...baseUser, role: 'admin', permissions: ['all'] };

// fixtures/edge-cases.ts - inherits base, adds edge conditions
export const unicodeUser = { ...baseUser, name: 'Joao da Silva', bio: 'Developer from Sao Paulo' };
export const maxLengthUser = { ...baseUser, name: 'A'.repeat(255) };
export const newUser = { ...baseUser, emailVerified: false, isActive: false, createdAt: new Date() };
