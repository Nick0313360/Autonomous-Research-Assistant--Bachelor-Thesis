// src/api/cache.ts
export class SWRCache {
  private cache = new Map<string, { data: unknown; timestamp: number; staleAt: number }>();

  constructor(private config: {
    maxAge: number;        // ms - serve from cache without revalidation
    staleWhileRevalidate: number;  // ms - serve stale while fetching fresh
    maxEntries: number;
  }) {}

  async get<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
    const entry = this.cache.get(key);
    const now = Date.now();
    if (entry && now < entry.timestamp + this.config.maxAge) {
      return entry.data as T;       // fresh - return immediately
    }
    if (entry && now < entry.staleAt) {
      fetcher().then(data => this.set(key, data));  // revalidate in background
      return entry.data as T;       // stale - return while revalidating
    }
    const data = await fetcher();   // expired or missing - fetch fresh
    this.set(key, data);
    return data;
  }
}
