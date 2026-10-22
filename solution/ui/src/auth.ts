// Sign-in seam. Components inject an AuthProvider and never import MSAL, so tests (and the Playwright stub in P05)
// can swap the implementation. MSAL objects and tokens never enter Vue reactive state.
import {
  InteractionRequiredAuthError,
  PublicClientApplication,
  type AccountInfo,
  type IPublicClientApplication,
} from "@azure/msal-browser";
import type { InjectionKey } from "vue";
import type { RuntimeConfig } from "./config";

export interface Account {
  name: string;
  upn: string;
  homeAccountId: string;
}

export interface AuthProvider {
  signIn(): Promise<void>;
  signOut(): Promise<void>;
  /** A fresh access token for chat-api. May redirect to sign in, in which case it never resolves. */
  getToken(): Promise<string>;
  account(): Account | null;
}

export const AUTH_KEY: InjectionKey<AuthProvider> = Symbol("auth");

/** Display name and UPN from an access token's claims. Display only: chat-api validates the token. */
export function identityFromToken(token: string): { name: string | null; upn: string | null } {
  try {
    const part = token.split(".")[1] ?? "";
    const base64 = part.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(part.length / 4) * 4, "=");
    const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
    const claims = JSON.parse(new TextDecoder().decode(bytes)) as Record<string, unknown>;
    const text = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
    return { name: text(claims.name), upn: text(claims.preferred_username) ?? text(claims.upn) };
  } catch {
    return { name: null, upn: null };
  }
}

function toAccount(info: AccountInfo): Account {
  return { name: info.name ?? info.username, upn: info.username, homeAccountId: info.homeAccountId };
}

export class MsalAuthProvider implements AuthProvider {
  private readonly scopes: string[];

  private constructor(private readonly client: IPublicClientApplication, blueprintAppId: string) {
    this.scopes = [`api://${blueprintAppId}/access_as_user`];
  }

  /** Initialises MSAL and completes any redirect before the app mounts. */
  static async create(config: RuntimeConfig): Promise<MsalAuthProvider> {
    const client = new PublicClientApplication({
      auth: {
        clientId: config.spaAppId,
        authority: `https://login.microsoftonline.com/${config.tenantId}`,
        redirectUri: `${window.location.origin}/`,
        postLogoutRedirectUri: `${window.location.origin}/`,
      },
      cache: { cacheLocation: "sessionStorage" },
    });
    await client.initialize();
    const result = await client.handleRedirectPromise();
    if (result?.account) client.setActiveAccount(result.account);
    else if (!client.getActiveAccount()) {
      const [first] = client.getAllAccounts();
      if (first) client.setActiveAccount(first);
    }
    return new MsalAuthProvider(client, config.blueprintAppId);
  }

  account(): Account | null {
    const info = this.client.getActiveAccount();
    return info ? toAccount(info) : null;
  }

  async signIn(): Promise<void> {
    await this.client.loginRedirect({ scopes: this.scopes, prompt: "select_account" });
  }

  async signOut(): Promise<void> {
    const account = this.client.getActiveAccount() ?? undefined;
    await this.client.logoutRedirect({ account });
  }

  async getToken(): Promise<string> {
    const account = this.client.getActiveAccount();
    if (!account) {
      await this.signIn();
      return new Promise<string>(() => undefined);
    }
    try {
      return (await this.client.acquireTokenSilent({ scopes: this.scopes, account })).accessToken;
    } catch (error) {
      if (error instanceof InteractionRequiredAuthError) {
        await this.client.acquireTokenRedirect({ scopes: this.scopes, account });
        return new Promise<string>(() => undefined);
      }
      throw error;
    }
  }
}
