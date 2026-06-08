// mocks/error-handlers.ts - overlay these for error-state testing
export const errorHandlers = [
  // Rate limiting (429)
  http.get('/api/*', () =>
    HttpResponse.json(
      { error: 'Too Many Requests', retryAfter: 30 },
      { status: 429, headers: { 'Retry-After': '30' } },
    ),
  ),

  // Server error (500) - intermittent
  http.get('/api/users', () => {
    if (Math.random() < 0.3) {
      return HttpResponse.json({ error: 'Internal Server Error' }, { status: 500 });
    }
    return HttpResponse.json({ data: generateUsers(20) });
  }),

  // Slow response for timeout testing
  http.get('/api/reports/*', async () => {
    await delay(15000); // 15s delay
    return HttpResponse.json({ data: [] });
  }),
];
