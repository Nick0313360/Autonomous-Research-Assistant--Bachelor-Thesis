// factories/user.factory.ts
import { faker } from '@faker-js/faker';

let sequence = 0;

export function createUser(overrides?: Partial<User>): User {
  const createdAt = overrides?.createdAt ?? faker.date.past({ years: 1 });
  return {
    id: randomUUID(),
    email: `user-${++sequence}@example.com`,
    name: faker.person.fullName(),
    role: 'member',
    isActive: true,
    createdAt,
    updatedAt: faker.date.between({ from: createdAt, to: new Date() }),
    ...overrides,
  };
}

// Convenience builders for common scenarios
export const createAdmin = (o?: Partial<User>) => createUser({ role: 'admin', ...o });
export const createInactiveUser = (o?: Partial<User>) => createUser({ isActive: false, ...o });

// Batch generation with relationships
export function createUserWithPosts(postCount = 3, overrides?: Partial<User>) {
  const user = createUser(overrides);
  const posts = Array.from({ length: postCount }, () =>
    createPost({ authorId: user.id, createdAt: user.createdAt }),
  );
  return { user, posts };
}

// Reset sequence between test suites
export function resetFactories() { sequence = 0; }
