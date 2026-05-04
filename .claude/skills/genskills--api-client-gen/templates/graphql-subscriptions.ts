// src/api/graphql/subscriptions.ts
import { createClient } from "graphql-ws";

export const subscriptionClient = createClient({
  url: getWsUrl(),
  connectionParams: async () => ({ authToken: await getToken() }),
  shouldRetry: () => true,
  retryAttempts: Infinity,
  retryWait: async (retries) => {
    await new Promise(r => setTimeout(r, Math.min(1000 * Math.pow(2, retries), 30000)));
  },
  on: {
    connected: () => console.log("[GQL-WS] Connected"),
    closed: (event) => console.warn("[GQL-WS] Closed", event),
    error: (error) => console.error("[GQL-WS] Error", error),
  },
});
