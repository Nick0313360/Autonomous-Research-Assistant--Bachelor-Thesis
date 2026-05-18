import { PrismaClient } from '@prisma/client';
import { faker } from '@faker-js/faker';

const prisma = new PrismaClient();
faker.seed(42); // Deterministic output

async function main() {
  // Clear existing data in reverse dependency order
  await prisma.$transaction([
    prisma.comment.deleteMany(),
    prisma.post.deleteMany(),
    prisma.user.deleteMany(),
  ]);

  // Generate with relationships and realistic distributions
  const users = await Promise.all(
    Array.from({ length: 50 }, (_, i) =>
      prisma.user.create({
        data: {
          email: faker.internet.email(),
          name: faker.person.fullName(),
          role: faker.helpers.weightedArrayElement([
            { value: 'user', weight: 80 },
            { value: 'moderator', weight: 15 },
            { value: 'admin', weight: 5 },
          ]),
          createdAt: faker.date.past({ years: 2 }),
        },
      }),
    ),
  );

  // Posts with Zipf-distributed authorship (some users write many posts)
  // ... continues with relationship-aware generation
}

main()
  .catch(console.error)
  .finally(() => prisma.$disconnect());
