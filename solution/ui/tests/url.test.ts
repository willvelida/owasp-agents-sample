import { describe, expect, it, vi } from "vitest";
import { stripAuthParams, withoutAuthParams } from "../src/url";

describe("withoutAuthParams", () => {
  it("removes MSAL's post-logout state and keeps other parameters and the hash", () => {
    expect(withoutAuthParams("https://chat-ui.example/?state=eyJpZCI6IjEifQ%3d%3d")).toBe("/");
    expect(withoutAuthParams("https://chat-ui.example/a?keep=1&state=eyJ&code=x&session_state=s#frag")).toBe(
      "/a?keep=1#frag",
    );
    expect(withoutAuthParams("https://chat-ui.example/?error=access_denied&error_description=no")).toBe("/");
  });

  it("returns null when there is nothing to remove", () => {
    expect(withoutAuthParams("https://chat-ui.example/")).toBeNull();
    expect(withoutAuthParams("https://chat-ui.example/?keep=1")).toBeNull();
  });
});

describe("stripAuthParams", () => {
  it("replaces the history entry without navigating", () => {
    const history = { state: { k: 1 }, replaceState: vi.fn() } as unknown as History;
    stripAuthParams({ href: "https://chat-ui.example/?state=eyJ" } as Location, history);
    expect(history.replaceState).toHaveBeenCalledWith({ k: 1 }, "", "/");
  });

  it("leaves a clean URL alone", () => {
    const history = { state: null, replaceState: vi.fn() } as unknown as History;
    stripAuthParams({ href: "https://chat-ui.example/" } as Location, history);
    expect(history.replaceState).not.toHaveBeenCalled();
  });
});
