import { describe, expect, it } from "vitest";
import { identityFromToken } from "../src/auth";
import { ConfigError, validateConfig } from "../src/config";
import { ThreadPin } from "../src/threads";

describe("ThreadPin", () => {
  it("refuses a send under a different account and starts a new thread for it", () => {
    let n = 0;
    const pin = new ThreadPin(() => `t-${++n}`);
    expect(pin.claim("alice-home")).toEqual({ allowed: true, threadId: "t-1" });
    expect(pin.claim("alice-home")).toEqual({ allowed: true, threadId: "t-1" });
    expect(pin.claim("bob-home")).toEqual({ allowed: false, threadId: "t-2" });
    expect(pin.claim("bob-home")).toEqual({ allowed: true, threadId: "t-2" });
    expect(pin.claim("alice-home").allowed).toBe(false);
  });
});

const good = {
  tenantId: "e60bb76c-8fda-4ed4-a354-4836e3bfcbc3",
  spaAppId: "534ca50a-ef98-433a-ae90-cd30dca10c2f",
  blueprintAppId: "c7a41d39-67a4-4582-b343-a491dec17633",
  chatApiUrl: "https://chat-api.example.australiaeast.azurecontainerapps.io",
};

describe("validateConfig", () => {
  it("accepts the contract and normalises chatApiUrl to the endpoint", () => {
    expect(validateConfig(good).chatApiUrl).toBe("https://chat-api.example.australiaeast.azurecontainerapps.io/");
    expect(validateConfig({ ...good, chatApiUrl: "http://127.0.0.1:8000" }).chatApiUrl).toBe("http://127.0.0.1:8000/");
  });

  it.each([
    ["placeholder id", { ...good, spaAppId: "<guid>" }],
    ["missing id", { ...good, tenantId: undefined }],
    ["http to a remote host", { ...good, chatApiUrl: "http://chat-api.example" }],
    ["a path", { ...good, chatApiUrl: "https://chat-api.example/api" }],
    ["credentials in the URL", { ...good, chatApiUrl: "https://u:p@chat-api.example" }],
    ["javascript URL", { ...good, chatApiUrl: "javascript:alert(1)" }],
    ["an extra key such as a user oid", { ...good, aliceOid: "aaaaaaaa-0000-0000-0000-00000000a11c" }],
    ["not an object", ["x"]],
  ])("rejects %s", (_label, raw) => {
    expect(() => validateConfig(raw)).toThrow(ConfigError);
  });
});

function token(claims: Record<string, unknown>): string {
  const b64 = (o: unknown) => btoa(JSON.stringify(o)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${b64({ alg: "none" })}.${b64(claims)}.sig`;
}

describe("identityFromToken", () => {
  it("reads name and preferred_username, falling back to upn", () => {
    expect(identityFromToken(token({ name: "Alice Example", preferred_username: "alice@x" }))).toEqual({
      name: "Alice Example",
      upn: "alice@x",
    });
    expect(identityFromToken(token({ name: "Bob", upn: "bob@x" }))).toEqual({ name: "Bob", upn: "bob@x" });
  });

  it("handles non-ASCII names and malformed tokens", () => {
    const bytes = new TextEncoder().encode(JSON.stringify({ name: "Zoë", preferred_username: "z@x" }));
    const payload = btoa(String.fromCharCode(...bytes)).replace(/=+$/, "");
    expect(identityFromToken(`h.${payload}.s`).name).toBe("Zoë");
    expect(identityFromToken("garbage")).toEqual({ name: null, upn: null });
  });
});
