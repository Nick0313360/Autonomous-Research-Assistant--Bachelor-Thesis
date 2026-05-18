// src/api/testing/handlers.ts
import { http, HttpResponse } from "msw";

// Auto-generated from OpenAPI spec - one handler per endpoint
export const handlers = [
  http.get("/api/users", ({ request }) => {
    const url = new URL(request.url);
    const page = Number(url.searchParams.get("page") ?? 1);
    return HttpResponse.json(fixtures.users.paginatedList({ page }));
  }),

  http.get("/api/users/:id", ({ params }) => {
    const user = fixtures.users.byId(params.id as string);
    if (!user) return new HttpResponse(null, { status: 404 });
    return HttpResponse.json({ status: "success", data: user });
  }),

  http.post("/api/users", async ({ request }) => {
    const body = await request.json() as CreateUserInput;
    return HttpResponse.json({ status: "success", data: fixtures.users.create(body) }, { status: 201 });
  }),

  http.put("/api/users/:id", async ({ request, params }) => {
    const body = await request.json() as UpdateUserInput;
    return HttpResponse.json({ status: "success", data: fixtures.users.update(params.id as string, body) });
  }),

  http.delete("/api/users/:id", () => {
    return new HttpResponse(null, { status: 204 });
  }),

  // ... repeat for all resources
];

// Scenario overrides for testing edge cases
export const errorHandlers = {
  serverDown: http.get("/api/*", () => HttpResponse.error()),
  rateLimited: http.get("/api/*", () => HttpResponse.json(
    { error: { code: "RATE_LIMITED" } },
    { status: 429, headers: { "Retry-After": "60" } }
  )),
  unauthorized: http.get("/api/*", () => HttpResponse.json(
    { error: { code: "TOKEN_EXPIRED" } },
    { status: 401 }
  )),
};
