// src/api/client.ts
export class ApiClient {
  private baseUrl: string;
  private middlewares: Middleware[] = [];
  private authProvider: AuthProvider;
  private retryStrategy: RetryStrategy;
  private circuitBreaker: CircuitBreaker;
  private cache: ResponseCache;

  // Resource namespaces
  readonly users: UsersEndpoint;
  readonly posts: PostsEndpoint;
  readonly organizations: OrganizationsEndpoint;

  constructor(config: ApiClientConfig) { /* ... */ }

  use(middleware: Middleware): this { /* chainable */ }

  async request<T>(endpoint: EndpointDefinition<T>): Promise<ApiResponse<T>> {
    // Pipeline: auth -> signing -> dedup -> cache -> retry -> circuit break -> fetch -> log
  }
}

type Middleware = {
  name: string;
  onRequest?(ctx: RequestContext): Promise<RequestContext> | RequestContext;
  onResponse?(ctx: ResponseContext): Promise<ResponseContext> | ResponseContext;
  onError?(ctx: ErrorContext): Promise<ErrorContext> | ErrorContext;
};
