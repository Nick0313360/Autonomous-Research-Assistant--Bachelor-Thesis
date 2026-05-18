// src/api/graphql/cache.ts
import { InMemoryCache } from "@apollo/client";

export const cache = new InMemoryCache({
  typePolicies: {
    Query: {
      fields: {
        // Merge paginated lists correctly
        posts: relayStylePagination(["where", "orderBy"]),
        users: offsetLimitPagination(["filter"]),
      },
    },
    User: {
      keyFields: ["id"],
      fields: {
        fullName: { read: (_, { readField }) => `${readField("firstName")} ${readField("lastName")}` },
      },
    },
  },
});

// Optimistic cache update helper
export function optimisticUpdatePost(cache: ApolloCache<any>, postId: string, update: Partial<Post>) {
  cache.modify({
    id: cache.identify({ __typename: "Post", id: postId }),
    fields: Object.fromEntries(
      Object.entries(update).map(([key, value]) => [key, () => value])
    ),
  });
}
