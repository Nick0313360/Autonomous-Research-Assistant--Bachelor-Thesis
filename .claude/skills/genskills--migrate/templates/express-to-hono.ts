// Before (Express)
app.get('/api/hello', (req, res) => {
  res.json({ message: `Hello ${req.query.name}` });
});

// After (Hono)
import { Hono } from 'hono';
const app = new Hono();
app.get('/api/hello', (c) => {
  return c.json({ message: `Hello ${c.req.query('name')}` });
});
