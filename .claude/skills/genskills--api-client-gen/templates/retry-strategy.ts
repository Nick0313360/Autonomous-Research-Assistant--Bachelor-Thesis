// src/api/retry.ts
export interface RetryStrategy {
  maxRetries: number;
  shouldRetry(error: ApiError, attempt: number): boolean;
  getDelay(error: ApiError, attempt: number): number;
}

export const defaultRetryStrategy: RetryStrategy = {
  maxRetries: 3,
  shouldRetry(error, attempt) {
    if (error instanceof RateLimitError) return true;
    if (error instanceof NetworkError) return attempt < 3;
    if (error instanceof ServerError) return attempt < 2;
    return false;
  },
  getDelay(error, attempt) {
    if (error instanceof RateLimitError) return error.retryAfter * 1000;
    return Math.min(1000 * Math.pow(2, attempt) + Math.random() * 500, 30000);
  }
};

// --- Circuit breaker to avoid hammering a failing service ---
export class CircuitBreaker {
  private state: "closed" | "open" | "half-open" = "closed";
  private failureCount = 0;
  private lastFailure: Date | null = null;

  constructor(private config: {
    failureThreshold: number;     // trips after N failures
    resetTimeout: number;         // ms before trying again
    monitorWindow: number;        // ms window for counting failures
  }) {}

  async execute<T>(fn: () => Promise<T>): Promise<T> { /* ... */ }
}
