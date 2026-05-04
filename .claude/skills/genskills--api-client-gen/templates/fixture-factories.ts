// src/api/testing/fixtures.ts
import { faker } from "@faker-js/faker";

// Type-safe fixture factories with overrides
function createFactory<T>(defaults: () => T) {
  return {
    build: (overrides?: Partial<T>): T => ({ ...defaults(), ...overrides }),
    buildList: (count: number, overrides?: Partial<T>): T[] =>
      Array.from({ length: count }, () => ({ ...defaults(), ...overrides })),
  };
}

export const fixtures = {
  users: {
    ...createFactory<User>(() => ({
      id: UserId(faker.string.uuid()),
      email: faker.internet.email(),
      name: faker.person.fullName(),
      avatarUrl: faker.image.avatar(),
      bio: faker.helpers.maybe(() => faker.lorem.sentence()) ?? undefined,
      organizationId: OrganizationId(faker.string.uuid()),
    })),
    paginatedList: (params?: { page?: number; pageSize?: number }) => {
      const pageSize = params?.pageSize ?? 20;
      return {
        items: fixtures.users.buildList(pageSize),
        pagination: { type: "offset" as const, page: params?.page ?? 1, pageSize, totalPages: 5 },
        total: 100,
      };
    },
  },
  posts: {
    ...createFactory<Post>(() => ({
      id: PostId(faker.string.uuid()),
      title: faker.lorem.sentence(),
      body: faker.lorem.paragraphs(3),
      authorId: UserId(faker.string.uuid()),
      createdAt: faker.date.recent().toISOString(),
      updatedAt: faker.date.recent().toISOString(),
    })),
  },
};
