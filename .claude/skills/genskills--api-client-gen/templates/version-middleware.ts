// The client version tracks the API version it was generated from.
// Major version = API major version. Minor/patch = client improvements.
// Example: API v2 -> @myorg/api-client@2.x.x

// Version header sent with every request for server-side compatibility checks
const CLIENT_VERSION = "2.1.0";
const API_VERSION = "2024-01-15";  // date-based API versioning support

export const versionMiddleware: Middleware = {
  name: "versioning",
  onRequest(ctx) {
    return { ...ctx, request: { ...ctx.request, headers: {
      ...ctx.request.headers,
      "X-Client-Version": CLIENT_VERSION,
      "X-API-Version": API_VERSION,
    }}};
  }
};
