// src/api/graphql/persisted.ts
// Pre-hashed queries for production - avoids sending full query strings
export const persistedQueries: Record<string, string> = {
  "GetUser": "sha256:a1b2c3d4e5f6...",
  "ListPosts": "sha256:f6e5d4c3b2a1...",
};

export const persistedQueryLink = new ApolloLink((operation, forward) => {
  const hash = persistedQueries[operation.operationName];
  if (hash) {
    operation.extensions = { ...operation.extensions, persistedQuery: { version: 1, sha256Hash: hash } };
  }
  return forward(operation);
});
