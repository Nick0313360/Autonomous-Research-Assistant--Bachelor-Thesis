export const compressionMiddleware: Middleware = {
  name: "compression",
  onRequest(ctx) {
    return { ...ctx, request: { ...ctx.request, headers: {
      ...ctx.request.headers, "Accept-Encoding": "gzip, br, deflate"
    }}};
  },
  async onResponse(ctx) {
    const encoding = ctx.response.headers.get("Content-Encoding");
    if (encoding === "br") ctx.response.body = await decompressBrotli(ctx.response.rawBody);
    if (encoding === "gzip") ctx.response.body = await decompressGzip(ctx.response.rawBody);
    return ctx;
  }
};
