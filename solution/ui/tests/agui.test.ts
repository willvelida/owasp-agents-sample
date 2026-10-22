import { afterEach, describe, expect, it, vi } from "vitest";
import { IDLE_TIMEOUT_MS, SseParser, resumeBody, runBody, streamRun, type AgUiEvent } from "../src/agui";

function counter(): () => string {
  let n = 0;
  return () => `id-${++n}`;
}

describe("SseParser", () => {
  it("handles chunks split mid-line and mid-frame", () => {
    const parser = new SseParser();
    const events = [
      ...parser.push('da'),
      ...parser.push('ta: {"type":"A",'),
      ...parser.push('"n":1}\n'),
      ...parser.push("\ndata: {\"type\":\"B\"}\r\n\r"),
      ...parser.push("\n"),
    ];
    expect(events).toEqual([{ type: "A", n: 1 }, { type: "B" }]);
  });

  it("joins multi-line data with newlines and ignores comments and other fields", () => {
    const parser = new SseParser();
    const events = parser.push(': keepalive\n\nevent: x\nid: 7\ndata: {"type":"T",\ndata: "v":"a"}\n\n: ping\n\n');
    expect(events).toEqual([{ type: "T", v: "a" }]);
  });

  it("emits a trailing frame without a blank line on flush", () => {
    const parser = new SseParser();
    expect(parser.push('data: {"type":"LAST"}')).toEqual([]);
    expect(parser.flush()).toEqual([{ type: "LAST" }]);
  });

  it("rejects non-JSON and untyped events", () => {
    expect(() => new SseParser().push("data: <img src=x>\n\n")).toThrow();
    expect(() => new SseParser().push('data: {"no":"type"}\n\n')).toThrow();
  });
});

describe("request bodies", () => {
  it("run body has a fresh runId, only the new message, and empty envelope fields", () => {
    const newId = counter();
    const first = runBody("thread-1", "hello", newId);
    const second = runBody("thread-1", "again", newId);
    expect(first).toEqual({
      threadId: "thread-1",
      runId: "id-1",
      messages: [{ id: "id-2", role: "user", content: "hello" }],
      state: {},
      tools: [],
      context: [],
      forwardedProps: {},
    });
    expect(second.runId).not.toBe(first.runId);
    expect(second.messages).toHaveLength(1);
    expect(first).not.toHaveProperty("resume");
  });

  it("resume body batches two interrupts with a yes/no decision only", () => {
    const body = resumeBody(
      "thread-1",
      [
        { interruptId: "int-a", accepted: true },
        { interruptId: "int-b", accepted: false },
      ],
      counter(),
    );
    expect(body).toEqual({
      threadId: "thread-1",
      runId: "id-1",
      messages: [],
      state: {},
      tools: [],
      context: [],
      forwardedProps: {},
      resume: [
        { interruptId: "int-a", status: "resolved", payload: { accepted: true } },
        { interruptId: "int-b", status: "resolved", payload: { accepted: false } },
      ],
    });
  });
});

function sseResponse(chunks: string[], init?: ResponseInit): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" }, ...init });
}

describe("streamRun", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("sends the bearer and SSE headers to the configured URL only, without credentials", async () => {
    const fetchImpl = vi.fn(async () => sseResponse(['data: {"type":"RUN_STARTED"}\n\n', 'data: {"type":"RUN_FINISHED"}']));
    const events: AgUiEvent[] = [];
    const outcome = await streamRun({
      url: "http://127.0.0.1:8000",
      token: "tok",
      body: runBody("t", "hi", counter()),
      onEvent: (e) => events.push(e),
      fetchImpl,
    });
    expect(outcome).toEqual({ kind: "done" });
    expect(events.map((e) => e.type)).toEqual(["RUN_STARTED", "RUN_FINISHED"]);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:8000");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("omit");
    expect(init.headers).toEqual({
      Accept: "text/event-stream",
      "Content-Type": "application/json",
      Authorization: "Bearer tok",
    });
    expect(url).not.toContain("tok");
  });

  it.each([400, 401, 403, 500])("returns HTTP %i with a short body and never parses it as events", async (status) => {
    const onEvent = vi.fn();
    const body = 'data: {"type":"TEXT_MESSAGE_CONTENT","delta":"x"}\n\n' + "y".repeat(1000);
    const outcome = await streamRun({
      url: "http://127.0.0.1:8000",
      token: "tok",
      body: runBody("t", "hi"),
      onEvent,
      fetchImpl: async () => new Response(body, { status }),
    });
    expect(outcome.kind).toBe("http");
    if (outcome.kind === "http") {
      expect(outcome.status).toBe(status);
      expect(outcome.body.length).toBe(300);
    }
    expect(onEvent).not.toHaveBeenCalled();
  });

  function controlledStream(): { response: Response; send: (s: string) => void; end: () => void } {
    const encoder = new TextEncoder();
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const stream = new ReadableStream<Uint8Array>({ start: (c) => void (controller = c) });
    return {
      response: new Response(stream, { status: 200 }),
      send: (s) => controller.enqueue(encoder.encode(s)),
      end: () => controller.close(),
    };
  }

  function abortableFetch(response: Response): typeof fetch {
    return (async (_url: RequestInfo | URL, init?: RequestInit) => {
      init?.signal?.addEventListener("abort", () => {
        void response.body?.cancel().catch(() => undefined);
      });
      const reader = response.body!.getReader();
      // Re-wrap so an abort rejects the pending read, as fetch does.
      const wrapped = new ReadableStream<Uint8Array>({
        async pull(c) {
          const aborted = new Promise<never>((_, reject) =>
            init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))),
          );
          const { done, value } = await Promise.race([reader.read(), aborted]);
          if (done) c.close();
          else c.enqueue(value);
        },
      });
      return new Response(wrapped, { status: 200 });
    }) as typeof fetch;
  }

  it("aborts a stream that is idle for 180 s", async () => {
    vi.useFakeTimers();
    const s = controlledStream();
    const result = streamRun({
      url: "http://127.0.0.1:8000",
      token: "tok",
      body: runBody("t", "hi"),
      onEvent: () => undefined,
      fetchImpl: abortableFetch(s.response),
    });
    s.send('data: {"type":"RUN_STARTED"}\n\n');
    await vi.advanceTimersByTimeAsync(IDLE_TIMEOUT_MS - 1);
    await vi.advanceTimersByTimeAsync(2);
    await expect(result).resolves.toEqual({ kind: "timeout" });
  });

  it("does not abort a stream that keeps receiving keepalives", async () => {
    vi.useFakeTimers();
    const s = controlledStream();
    const events: AgUiEvent[] = [];
    const result = streamRun({
      url: "http://127.0.0.1:8000",
      token: "tok",
      body: runBody("t", "hi"),
      onEvent: (e) => events.push(e),
      fetchImpl: abortableFetch(s.response),
    });
    for (let i = 0; i < 20; i++) {
      s.send(": keepalive\n\n");
      await vi.advanceTimersByTimeAsync(15_000);
    }
    s.send('data: {"type":"RUN_FINISHED"}\n\n');
    s.end();
    await expect(result).resolves.toEqual({ kind: "done" });
    expect(events.map((e) => e.type)).toEqual(["RUN_FINISHED"]);
  });
});
