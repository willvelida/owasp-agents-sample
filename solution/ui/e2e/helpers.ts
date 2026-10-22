import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Page, Request } from "@playwright/test";

const fixtures = join(dirname(fileURLToPath(import.meta.url)), "fixtures");
export const CHAT_API = "https://chat-api.example.invalid/";

export function fixture(name: string): string {
  return readFileSync(join(fixtures, name), "utf8");
}

export interface Reply {
  status?: number;
  body: string;
}

export interface ChatRoutes {
  /** Bodies of the POSTs that reached chat-api, in order. */
  posts: Array<Record<string, unknown>>;
  /** Every request the page made, for host and header assertions. */
  requests: Request[];
}

/**
 * Routes /config.json to the committed dummy config and each chat-api POST to the next reply. Nothing leaves the
 * machine: the chat-api host is .invalid, and any other non-local request is aborted.
 */
export async function routeChat(page: Page, replies: Reply[]): Promise<ChatRoutes> {
  const routes: ChatRoutes = { posts: [], requests: [] };
  page.on("request", (request) => routes.requests.push(request));
  await page.route("**/config.json", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: fixture("config.json") }),
  );
  await page.route(`${CHAT_API}**`, async (route) => {
    const request = route.request();
    const cors = {
      "access-control-allow-origin": new URL(page.url()).origin,
      "access-control-allow-methods": "POST",
      "access-control-allow-headers": "authorization, content-type",
    };
    if (request.method() === "OPTIONS") return route.fulfill({ status: 200, headers: cors });
    routes.posts.push(JSON.parse(request.postData() ?? "{}") as Record<string, unknown>);
    const reply = replies.shift() ?? { status: 500, body: "no fixture left" };
    const status = reply.status ?? 200;
    return route.fulfill({
      status,
      headers: { ...cors, "content-type": status === 200 ? "text/event-stream" : "text/plain" },
      body: reply.body,
    });
  });
  await page.route(/^https?:\/\/(?!localhost|127\.0\.0\.1|chat-api\.example\.invalid)/, (route) => route.abort());
  return routes;
}

export async function send(page: Page, text: string): Promise<void> {
  await page.getByRole("textbox", { name: "Message" }).fill(text);
  await page.getByRole("button", { name: "Send" }).click();
}
