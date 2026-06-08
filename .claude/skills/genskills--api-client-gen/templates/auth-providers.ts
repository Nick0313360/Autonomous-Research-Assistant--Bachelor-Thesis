// src/api/auth.ts
export class TokenAuthProvider implements AuthProvider {
  private accessToken: string | null = null;
  private refreshToken: string | null = null;
  private refreshPromise: Promise<TokenPair> | null = null;
  private pendingRequests: Array<{
    resolve: (token: string) => void;
    reject: (error: Error) => void;
  }> = [];

  // Queues concurrent requests during token refresh so only one refresh fires
  async getAccessToken(): Promise<string> {
    if (this.isTokenValid(this.accessToken)) return this.accessToken!;
    if (this.refreshPromise) return this.waitForRefresh();
    return this.performRefresh();
  }

  private async performRefresh(): Promise<string> {
    this.refreshPromise = this.refreshTokens();
    try {
      const tokens = await this.refreshPromise;
      this.accessToken = tokens.accessToken;
      this.refreshToken = tokens.refreshToken;
      this.pendingRequests.forEach(r => r.resolve(tokens.accessToken));
      return tokens.accessToken;
    } catch (error) {
      this.pendingRequests.forEach(r => r.reject(error as Error));
      throw error;
    } finally {
      this.refreshPromise = null;
      this.pendingRequests = [];
    }
  }
}

// --- OAuth2 PKCE flow helpers ---
export class OAuth2PKCEProvider implements AuthProvider {
  async initiateAuth(): Promise<{ authUrl: string; state: string }> { /* ... */ }
  async handleCallback(code: string, state: string): Promise<TokenPair> { /* ... */ }
  private generateCodeVerifier(): string { /* ... */ }
  private generateCodeChallenge(verifier: string): Promise<string> { /* ... */ }
}

// --- API key rotation support ---
export class RotatingApiKeyProvider implements AuthProvider {
  constructor(private keys: string[], private rotationStrategy: "round-robin" | "failover") {}
  async getApiKey(): Promise<string> { /* ... */ }
  markKeyFailed(key: string): void { /* ... */ }
}

// --- Session-based auth with CSRF ---
export class SessionAuthProvider implements AuthProvider {
  private csrfToken: string | null = null;
  async ensureCsrfToken(): Promise<string> { /* ... */ }
  applyToRequest(request: RequestInit): RequestInit {
    return { ...request, headers: { ...request.headers, "X-CSRF-Token": this.csrfToken! },
      credentials: "include" };
  }
}

// --- Multi-tenant auth headers ---
export class MultiTenantAuthProvider implements AuthProvider {
  constructor(private tenantResolver: () => string | Promise<string>) {}
  async applyToRequest(request: RequestInit): Promise<RequestInit> {
    const tenantId = await this.tenantResolver();
    return { ...request, headers: { ...request.headers, "X-Tenant-Id": tenantId } };
  }
}
