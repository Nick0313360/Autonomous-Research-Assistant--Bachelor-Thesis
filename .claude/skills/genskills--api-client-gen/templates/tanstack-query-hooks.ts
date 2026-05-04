// src/api/hooks/useUsers.ts
import { useQuery, useMutation, useInfiniteQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";

// --- Standard query hook ---
export function useUser(id: UserId, options?: Partial<UseQueryOptions<UserWithRelations>>) {
  return useQuery({
    queryKey: queryKeys.users.detail(id),
    queryFn: ({ signal }) => api.users.get(id, { signal }),
    staleTime: 5 * 60 * 1000,
    ...options,
  });
}

// --- Suspense-ready variant ---
export function useUserSuspense(id: UserId) {
  return useSuspenseQuery({
    queryKey: queryKeys.users.detail(id),
    queryFn: ({ signal }) => api.users.get(id, { signal }),
  });
}

// --- List with filters ---
export function useUsers(filters: UserFilters = {}, options?: Partial<UseQueryOptions>) {
  return useQuery({
    queryKey: queryKeys.users.list(filters),
    queryFn: ({ signal }) => api.users.list(filters, { signal }),
    placeholderData: keepPreviousData,
    ...options,
  });
}

// --- Infinite scroll ---
export function useUsersInfinite(filters: Omit<UserFilters, "cursor">) {
  return useInfiniteQuery({
    queryKey: queryKeys.posts.infinite(filters),
    queryFn: ({ pageParam, signal }) => api.users.list({ ...filters, cursor: pageParam }, { signal }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.pagination.type === "cursor" ? lastPage.pagination.nextCursor ?? undefined : undefined,
  });
}

// --- Mutation with optimistic update ---
export function useUpdateUser() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: UserId; data: UpdateUserInput }) => api.users.update(id, data),
    onMutate: async ({ id, data }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.users.detail(id) });
      const previous = queryClient.getQueryData<User>(queryKeys.users.detail(id));
      queryClient.setQueryData(queryKeys.users.detail(id), (old: User | undefined) =>
        old ? { ...old, ...data } : old
      );
      return { previous };
    },
    onError: (_err, { id }, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.users.detail(id), context.previous);
      }
    },
    onSettled: (_data, _err, { id }) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.users.detail(id) });
      queryClient.invalidateQueries({ queryKey: queryKeys.users.lists() });
    },
  });
}

// --- Delete with optimistic removal from list ---
export function useDeleteUser() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: UserId) => api.users.delete(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.users.lists() });
      const previousLists = queryClient.getQueriesData({ queryKey: queryKeys.users.lists() });
      queryClient.setQueriesData({ queryKey: queryKeys.users.lists() }, (old: PaginatedResponse<User> | undefined) =>
        old ? { ...old, items: old.items.filter(u => u.id !== id), total: old.total - 1 } : old
      );
      return { previousLists };
    },
    onError: (_err, _id, context) => {
      context?.previousLists.forEach(([key, data]) => queryClient.setQueryData(key, data));
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
    },
  });
}
