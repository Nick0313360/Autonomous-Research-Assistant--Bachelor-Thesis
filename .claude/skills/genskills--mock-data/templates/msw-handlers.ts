// mocks/handlers.ts
import { http, HttpResponse, delay } from 'msw';
import { generateUser, generateUsers } from './factories';

export const handlers = [
  // GET /api/users - paginated list
  http.get('/api/users', async ({ request }) => {
    const url = new URL(request.url);
    const page = Number(url.searchParams.get('page') ?? 1);
    const limit = Number(url.searchParams.get('limit') ?? 20);
    const total = 150;
    const users = generateUsers(limit, { seed: page });

    await delay(150); // Realistic network delay
    return HttpResponse.json({
      data: users,
      meta: { page, limit, total, totalPages: Math.ceil(total / limit) },
    });
  }),

  // GET /api/users/:id - single resource
  http.get('/api/users/:id', async ({ params }) => {
    await delay(80);
    return HttpResponse.json(generateUser({ id: params.id as string }));
  }),

  // POST /api/users - create with validation
  http.post('/api/users', async ({ request }) => {
    const body = await request.json();
    await delay(200);
    // Simulate validation errors ~10% of the time in development
    if (Math.random() < 0.1) {
      return HttpResponse.json(
        { error: 'Validation failed', fields: { email: 'already taken' } },
        { status: 422 },
      );
    }
    return HttpResponse.json(generateUser(body), { status: 201 });
  }),
];
