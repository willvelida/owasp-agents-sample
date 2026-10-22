// E2E-only AuthProvider. main.ts imports it only when Vite runs in "e2e" mode, so production builds never contain it;
// CI fails if dist/ holds STUB_MARKER. The token is fake and only ever reaches Playwright's routed responses.
import type { Account, AuthProvider } from "./auth";

export const STUB_MARKER = "biotrackr-e2e-stub-auth-provider";

function base64Url(value: unknown): string {
  return btoa(JSON.stringify(value)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export class StubAuthProvider implements AuthProvider {
  private signedIn = true;
  private readonly identity: Account = {
    name: "Alice Example",
    upn: "alice@e2e.invalid",
    homeAccountId: "e2e-alice-home",
  };

  account(): Account | null {
    return this.signedIn ? this.identity : null;
  }

  async signIn(): Promise<void> {
    this.signedIn = true;
  }

  async signOut(): Promise<void> {
    this.signedIn = false;
  }

  async getToken(): Promise<string> {
    const claims = { name: this.identity.name, preferred_username: this.identity.upn, marker: STUB_MARKER };
    return `${base64Url({ alg: "none", typ: "JWT" })}.${base64Url(claims)}.e2e`;
  }
}
