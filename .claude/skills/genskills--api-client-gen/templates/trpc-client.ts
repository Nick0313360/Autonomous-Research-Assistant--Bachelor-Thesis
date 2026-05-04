// src/api/trpc.ts
import { createTRPCProxyClient, httpBatchLink, splitLink, wsLink, createWSClient } from "@trpc/client";
import type { AppRouter } from "@server/routers/_app";  // inferred from detected router

// --- Batched HTTP client ---
export const trpc = createTRPCProxyClient<AppRouter>({
  links: [
    splitLink({
      condition: (op) => op.type === "subscription",
      true: wsLink({ client: createWSClient({ url: getWsUrl() }) }),
      false: httpBatchLink({
        url: getBaseUrl() + "/api/trpc",
        maxURLLength: 2048,
        headers: () => ({ Authorization: `Bearer ${getToken()}` }),
      }),
    }),
  ],
  transformer: superjson,
});

// --- Type-safe caller for server-side usage (Next.js Server Components, etc.) ---
export const serverTrpc = appRouter.createCaller({
  session: null, // populated at call site
  db: prisma,
});

// --- React hooks via @trpc/react-query ---
// Auto-generated from router shape - provides trpc.user.list.useQuery(), etc.
export const trpcReact = createTRPCReact<AppRouter>();

// --- Subscription helper with reconnection ---
export function useSubscription<T>(
  path: string,
  input: unknown,
  handlers: { onData: (data: T) => void; onError?: (err: TRPCClientError<AppRouter>) => void }
) { /* generates typed subscription hook with auto-reconnect */ }
