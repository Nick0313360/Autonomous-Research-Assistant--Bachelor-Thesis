// Resolver wrapping existing REST service
const resolvers = {
  Query: {
    user: async (_: unknown, { id }: { id: string }) => {
      // Phase 1: call existing REST internally
      const res = await fetch(`http://internal-api/users/${id}`);
      return res.json();
      // Phase 2 (later): call database directly
    },
  },
};
