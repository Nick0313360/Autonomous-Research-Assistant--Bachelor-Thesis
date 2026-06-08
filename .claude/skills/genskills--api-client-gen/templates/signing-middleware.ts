// src/api/middleware.ts

export const awsSigV4Middleware: Middleware = {
  name: "aws-sigv4",
  async onRequest(ctx) {
    const { method, url, body, headers } = ctx.request;
    const signature = await signV4({
      method, url, body,
      region: ctx.config.awsRegion,
      service: ctx.config.awsService,
      credentials: await ctx.config.getAwsCredentials(),
    });
    return { ...ctx, request: { ...ctx.request, headers: { ...headers, ...signature.headers } } };
  }
};

export const hmacSigningMiddleware = (secret: string, algorithm = "sha256"): Middleware => ({
  name: "hmac-signing",
  async onRequest(ctx) {
    const timestamp = Date.now().toString();
    const payload = `${ctx.request.method}:${ctx.request.url}:${timestamp}:${ctx.request.body ?? ""}`;
    const signature = await hmacSign(payload, secret, algorithm);
    return { ...ctx, request: { ...ctx.request, headers: {
      ...ctx.request.headers, "X-Signature": signature, "X-Timestamp": timestamp
    }}};
  }
});
