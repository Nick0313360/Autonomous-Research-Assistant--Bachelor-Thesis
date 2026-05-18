// Using supertest or similar
describe('API contract: GET /api/users/:id', () => {
  it('returns 200 with user object shape', async () => {
    const res = await request(app).get('/api/users/1');
    expect(res.status).toBe(200);
    expect(res.body).toMatchObject({
      id: expect.any(Number),
      name: expect.any(String),
      email: expect.any(String),
      createdAt: expect.any(String),
    });
  });

  it('returns 404 for unknown user', async () => {
    const res = await request(app).get('/api/users/99999');
    expect(res.status).toBe(404);
  });
});
