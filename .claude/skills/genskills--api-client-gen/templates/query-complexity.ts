// src/api/graphql/complexity.ts
// Calculates estimated query cost before sending to avoid server rejection
export function calculateComplexity(query: DocumentNode, variables: Record<string, unknown>): number {
  const weights: Record<string, number> = {
    scalar: 0,
    object: 1,
    list: (variables["first"] as number ?? variables["limit"] as number ?? 10),
    connection: (variables["first"] as number ?? 10) + 1,
  };
  // Walks the AST and sums weights; rejects if over threshold
  return walkAndSum(query, weights);
}
