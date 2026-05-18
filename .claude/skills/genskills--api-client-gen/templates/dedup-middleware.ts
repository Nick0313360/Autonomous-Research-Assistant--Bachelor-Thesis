export const deduplicationMiddleware: Middleware = {
  name: "dedup",
  _inflight: new Map<string, Promise<Response>>(),
  async onRequest(ctx) {
    if (ctx.request.method !== "GET") return ctx;
    const key = `${ctx.request.method}:${ctx.request.url}`;
    if (this._inflight.has(key)) {
      ctx.dedupedFrom = this._inflight.get(key);
    } else {
      this._inflight.set(key, ctx.responsePromise);
      ctx.responsePromise.finally(() => this._inflight.delete(key));
    }
    return ctx;
  }
};
