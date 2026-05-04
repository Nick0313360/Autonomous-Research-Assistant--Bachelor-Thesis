// src/api/testing/recorder.ts
export class RequestRecorder {
  private recordings: Map<string, { request: RequestInit; response: Response; timestamp: number }[]> = new Map();
  private mode: "record" | "playback" | "passthrough" = "passthrough";

  setMode(mode: "record" | "playback" | "passthrough"): void { this.mode = mode; }

  async intercept(url: string, init: RequestInit): Promise<Response> {
    const key = `${init.method ?? "GET"}:${url}`;
    if (this.mode === "playback") {
      const recorded = this.recordings.get(key)?.shift();
      if (recorded) return new Response(JSON.stringify(recorded.response.body), recorded.response);
      throw new Error(`No recording found for ${key}`);
    }
    const response = await fetch(url, init);
    if (this.mode === "record") {
      const entries = this.recordings.get(key) ?? [];
      entries.push({ request: init, response: response.clone(), timestamp: Date.now() });
      this.recordings.set(key, entries);
    }
    return response;
  }

  async saveToFile(path: string): Promise<void> { /* serialize to JSON */ }
  async loadFromFile(path: string): Promise<void> { /* deserialize from JSON */ }
}
