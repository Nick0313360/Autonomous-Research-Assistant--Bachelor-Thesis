// src/api/hooks/queryKeys.ts
export const queryKeys = {
  users: {
    all:    ["users"] as const,
    lists:  ()              => [...queryKeys.users.all, "list"] as const,
    list:   (filters: UserFilters) => [...queryKeys.users.lists(), filters] as const,
    details:  ()            => [...queryKeys.users.all, "detail"] as const,
    detail: (id: UserId)    => [...queryKeys.users.details(), id] as const,
    posts:  (id: UserId)    => [...queryKeys.users.detail(id), "posts"] as const,
  },
  posts: {
    all:    ["posts"] as const,
    lists:  ()              => [...queryKeys.posts.all, "list"] as const,
    list:   (filters: PostFilters) => [...queryKeys.posts.lists(), filters] as const,
    detail: (id: PostId)    => [...queryKeys.posts.all, "detail", id] as const,
    infinite: (filters: PostFilters) => [...queryKeys.posts.lists(), "infinite", filters] as const,
  },
} as const;
