// src/api/realtime.ts

export type WebSocketEvent =
  | { type: "user.updated"; payload: User }
  | { type: "post.created"; payload: Post }
  | { type: "notification.new"; payload: Notification }
  | { type: "system.maintenance"; payload: { startsAt: string; duration: number } };

export class TypedWebSocketClient {
  private ws: WebSocket | null = null;
  private listeners = new Map<string, Set<Function>>();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;

  constructor(private config: {
    url: string;
    protocols?: string[];
    getAuthToken: () => Promise<string>;
    heartbeatIntervalMs?: number;
  }) {}

  connect(): void {
    // Establishes connection with auth, sets up heartbeat, and binds reconnect logic
  }

  on<E extends WebSocketEvent["type"]>(
    event: E,
    handler: (payload: Extract<WebSocketEvent, { type: E }>["payload"]) => void
  ): () => void {
    // Returns unsubscribe function
  }

  private reconnect(): void {
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts) + Math.random() * 1000, 30000);
    setTimeout(() => {
      this.reconnectAttempts++;
      this.connect();
    }, delay);
  }

  disconnect(): void {
    if (this.heartbeatInterval) clearInterval(this.heartbeatInterval);
    this.ws?.close(1000, "Client disconnect");
    this.ws = null;
  }
}
