// src/api/types.ts - Core types with advanced patterns

// --- Branded types for type-safe IDs ---
declare const __brand: unique symbol;
type Brand<T, B extends string> = T & { readonly [__brand]: B };

export type UserId = Brand<string, "UserId">;
export type PostId = Brand<string, "PostId">;
export type OrganizationId = Brand<string, "OrganizationId">;

// Brand constructor helpers
export const UserId = (id: string) => id as UserId;
export const PostId = (id: string) => id as PostId;

// --- Discriminated union responses ---
export type ApiResponse<T> =
  | { status: "success"; data: T; meta: ResponseMeta }
  | { status: "error"; error: ApiError; meta: ResponseMeta };

// --- Strict null checking for optional fields ---
export interface User {
  id: UserId;
  email: string;
  name: string;
  avatarUrl: string | null;        // explicitly nullable
  bio?: string | undefined;         // truly optional (may not be present)
  organizationId: OrganizationId;
}

// --- Generic pagination wrapper ---
export interface PaginatedResponse<T> {
  items: T[];
  pagination: CursorPagination | OffsetPagination;
  total: number;
}

export interface CursorPagination {
  type: "cursor";
  nextCursor: string | null;
  previousCursor: string | null;
  hasMore: boolean;
}

export interface OffsetPagination {
  type: "offset";
  page: number;
  pageSize: number;
  totalPages: number;
}

// --- Conditional types for response variants ---
type UserRelations = "posts" | "organization" | "followers";

export type UserWithRelations<R extends UserRelations = never> = User &
  ([R] extends [never] ? {} :
  ("posts" extends R ? { posts: Post[] } : {}) &
  ("organization" extends R ? { organization: Organization } : {}) &
  ("followers" extends R ? { followers: User[] } : {}));

// --- Builder pattern for complex queries ---
export interface QueryBuilder<T> {
  where(field: keyof T, op: FilterOperator, value: unknown): this;
  orderBy(field: keyof T, direction: "asc" | "desc"): this;
  include<R extends string>(...relations: R[]): this;
  limit(n: number): this;
  offset(n: number): this;
  cursor(token: string): this;
  build(): QueryParams;
  execute(): Promise<PaginatedResponse<T>>;
}

// --- Per-endpoint error types ---
export type CreateUserError =
  | { code: "VALIDATION_ERROR"; fields: Record<string, string[]> }
  | { code: "EMAIL_TAKEN"; existingUserId: UserId }
  | { code: "ORGANIZATION_NOT_FOUND"; organizationId: OrganizationId };

export type AuthError =
  | { code: "TOKEN_EXPIRED"; expiredAt: string }
  | { code: "TOKEN_INVALID"; reason: string }
  | { code: "INSUFFICIENT_PERMISSIONS"; required: string[]; actual: string[] };
