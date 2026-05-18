// src/api/hooks/invalidation.ts
export const invalidationRules: Record<string, (queryClient: QueryClient) => void> = {
  "users.create": (qc) => qc.invalidateQueries({ queryKey: queryKeys.users.lists() }),
  "users.update": (qc) => qc.invalidateQueries({ queryKey: queryKeys.users.all }),
  "users.delete": (qc) => {
    qc.invalidateQueries({ queryKey: queryKeys.users.all });
    qc.invalidateQueries({ queryKey: queryKeys.posts.all }); // cascade - user's posts may change
  },
};
