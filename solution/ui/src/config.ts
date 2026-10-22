// Runtime settings come from /config.json (written by the container at start, or by hand for local dev), not the
// bundle. Only non-secret ids and the chat-api URL; never user oids or UPNs.
import type { InjectionKey } from "vue";

export interface RuntimeConfig {
  tenantId: string;
  spaAppId: string;
  blueprintAppId: string;
  /** Normalised to the origin plus "/", the AG-UI endpoint. */
  chatApiUrl: string;
}

export const CONFIG_KEY: InjectionKey<RuntimeConfig> = Symbol("runtime-config");

const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const KEYS = ["tenantId", "spaAppId", "blueprintAppId", "chatApiUrl"] as const;
const LOOPBACK = new Set(["127.0.0.1", "localhost", "[::1]"]);

export class ConfigError extends Error {}

function chatApiUrl(value: unknown): string {
  if (typeof value !== "string") throw new ConfigError("chatApiUrl must be a URL");
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new ConfigError("chatApiUrl must be an absolute URL");
  }
  const loopbackHttp = url.protocol === "http:" && LOOPBACK.has(url.hostname);
  if (url.protocol !== "https:" && !loopbackHttp) throw new ConfigError("chatApiUrl must use https (http only on loopback)");
  if (url.username || url.password || url.search || url.hash || url.pathname !== "/") {
    throw new ConfigError("chatApiUrl must be an origin with no path, query, or credentials");
  }
  return `${url.origin}/`;
}

export function validateConfig(raw: unknown): RuntimeConfig {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) throw new ConfigError("config.json must be an object");
  const source = raw as Record<string, unknown>;
  const extra = Object.keys(source).filter((k) => !(KEYS as readonly string[]).includes(k));
  if (extra.length > 0) throw new ConfigError(`config.json has unexpected keys: ${extra.join(", ")}`);
  for (const key of ["tenantId", "spaAppId", "blueprintAppId"] as const) {
    const value = source[key];
    if (typeof value !== "string" || !GUID.test(value)) throw new ConfigError(`${key} must be a GUID`);
  }
  return {
    tenantId: source.tenantId as string,
    spaAppId: source.spaAppId as string,
    blueprintAppId: source.blueprintAppId as string,
    chatApiUrl: chatApiUrl(source.chatApiUrl),
  };
}

export async function loadConfig(fetchImpl: typeof fetch = fetch): Promise<RuntimeConfig> {
  const response = await fetchImpl("/config.json", { cache: "no-store", credentials: "omit" });
  if (!response.ok) throw new ConfigError(`config.json returned HTTP ${response.status}`);
  return validateConfig(await response.json());
}
