// src/api/errors.ts

// --- Base error with full context ---
export class ApiError extends Error {
  readonly endpoint: string;
  readonly method: string;
  readonly statusCode: number | null;
  readonly requestId: string | null;
  readonly timestamp: Date;
  readonly retryable: boolean;

  constructor(params: ApiErrorParams) { /* ... */ }
}

// --- Discriminated error subclasses ---
export class NetworkError extends ApiError {
  readonly kind = "network";
  readonly cause: "timeout" | "dns" | "connection_refused" | "offline";
  readonly retryable = true;
}

export class AuthenticationError extends ApiError {
  readonly kind = "auth";
  readonly reason: "token_expired" | "token_invalid" | "forbidden" | "mfa_required";
  readonly retryable = false; // but may trigger token refresh + retry
}

export class ValidationError extends ApiError {
  readonly kind = "validation";
  readonly fieldErrors: Record<string, string[]>;
  readonly retryable = false;
}

export class RateLimitError extends ApiError {
  readonly kind = "rate_limit";
  readonly retryAfter: number; // seconds
  readonly limit: number;
  readonly remaining: number;
  readonly retryable = true;
}

export class ServerError extends ApiError {
  readonly kind = "server";
  readonly retryable = true;
}

// --- Type guard for error discrimination ---
export function isApiError(error: unknown): error is ApiError { /* ... */ }
export function isNetworkError(error: unknown): error is NetworkError { /* ... */ }
export function isRetryable(error: unknown): boolean { /* ... */ }

// --- Error discrimination utility ---
export function matchApiError<T>(error: ApiError, handlers: {
  network?: (e: NetworkError) => T;
  auth?: (e: AuthenticationError) => T;
  validation?: (e: ValidationError) => T;
  rateLimit?: (e: RateLimitError) => T;
  server?: (e: ServerError) => T;
  default: (e: ApiError) => T;
}): T { /* ... */ }
