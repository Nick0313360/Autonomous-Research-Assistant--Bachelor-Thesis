export const loggingMiddleware = (config: {
  redactHeaders: string[];        // ["Authorization", "Cookie", "X-Api-Key"]
  redactBodyFields: string[];     // ["password", "ssn", "creditCard"]
  logLevel: "debug" | "info";
}): Middleware => ({
  name: "logging",
  onRequest(ctx) {
    const safeHeaders = redactKeys(ctx.request.headers, config.redactHeaders);
    const safeBody = redactKeys(ctx.request.body, config.redactBodyFields);
    logger[config.logLevel](`-> ${ctx.request.method} ${ctx.request.url}`, { headers: safeHeaders, body: safeBody });
    return ctx;
  },
  onResponse(ctx) {
    const safeBody = redactKeys(ctx.response.body, config.redactBodyFields);
    logger[config.logLevel](`<- ${ctx.response.status} (${ctx.duration}ms)`, { body: safeBody });
    return ctx;
  }
});
