// mocks/ws-handlers.ts
import { ws } from 'msw';

const notifications = ws.link('wss://api.example.com/ws');
export const wsHandlers = [
  notifications.addEventListener('connection', ({ client }) => {
    // Send initial state
    client.send(JSON.stringify({ type: 'connected', userId: 'user_1' }));

    // Simulate periodic events
    const interval = setInterval(() => {
      client.send(JSON.stringify({
        type: 'notification',
        data: generateNotification(),
        timestamp: new Date().toISOString(),
      }));
    }, 5000 + Math.random() * 10000);

    client.addEventListener('close', () => clearInterval(interval));
  }),
];
