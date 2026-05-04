// src/api/hooks/prefetch.ts
import { QueryClient, dehydrate } from "@tanstack/react-query";

export async function prefetchUser(queryClient: QueryClient, id: UserId) {
  await queryClient.prefetchQuery({
    queryKey: queryKeys.users.detail(id),
    queryFn: () => api.users.get(id),
    staleTime: 5 * 60 * 1000,
  });
}

// Next.js App Router usage
export async function generateUserPageProps(id: UserId) {
  const queryClient = new QueryClient();
  await prefetchUser(queryClient, UserId(id));
  return { dehydratedState: dehydrate(queryClient) };
}
