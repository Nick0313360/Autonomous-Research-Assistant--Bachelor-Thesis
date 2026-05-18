// src/api/realtime-sse.ts
export class SSEClient<Events extends Record<string, unknown>> {
  private eventSource: EventSource | null = null;
  private retryCount = 0;

  constructor(private config: {
    url: string;
    withCredentials?: boolean;
    headers?: Record<string, string>; // Requires polyfill (e.g., eventsource-polyfill) for custom headers
  }) {}

  subscribe<E extends keyof Events & string>(
    event: E,
    handler: (data: Events[E]) => void,
    options?: { signal?: AbortSignal }
  ): () => void { /* ... */ }

  // Fallback to long-polling if SSE is unavailable
  private fallbackToLongPolling(): void {
    const poll = async () => {
      try {
        const res = await fetch(this.config.url, { headers: { Accept: "application/json" } });
        const events = await res.json();
        events.forEach((e: any) => this.dispatch(e.type, e.data));
      } catch { /* backoff */ }
      if (!this.closed) setTimeout(poll, this.getPollingInterval());
    };
    poll();
  }
}
