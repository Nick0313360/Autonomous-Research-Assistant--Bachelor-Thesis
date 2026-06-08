// Before (Express)
const express = require('express');
const app = express();
app.use(express.json());
app.get('/users/:id', async (req, res) => {
  const user = await getUser(req.params.id);
  res.json(user);
});

// After (Fastify)
import Fastify from 'fastify';
const app = Fastify({ logger: true });
app.get<{ Params: { id: string } }>('/users/:id', {
  schema: {
    params: { type: 'object', properties: { id: { type: 'string' } }, required: ['id'] },
    response: { 200: { type: 'object', properties: { name: { type: 'string' } } } },
  },
  handler: async (request, reply) => {
    const user = await getUser(request.params.id);
    return user; // Fastify auto-serializes
  },
});
