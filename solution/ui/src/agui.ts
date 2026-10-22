// AG-UI transport: the CLI's request contract (client/src/biotrackr_client/cli.py) over fetch and SSE.
// Framework-free so it can be tested without a DOM.
import type { Interrupt, ResumeEntry, RunAgentInput } from "@ag-ui/core";

// Matches the CLI's per-read timeout: reports can take a minute end to end. Reset on every chunk, keepalives included.
export const IDLE_TIMEOUT_MS = 180_000;
const ERROR_BODY_CHARS = 300;

export interface AgUiEvent {
  type: string;
  [key: string]: unknown;
}

export interface Decision {
  interruptId: Interrupt["id"];
  accepted: boolean;
}

export type NewId = () => string;
const uuid: NewId = () => crypto.randomUUID();

function envelope(threadId: string, newId: NewId): RunAgentInput {
  return {
    threadId,
    runId: newId(),
    messages: [],
    state: {},
    tools: [],
    context: [],
    forwardedProps: {},
  };
}

/** A run carries only the new user message; the server keeps history per thread and per signed-in user. */
export function runBody(threadId: string, message: string, newId: NewId = uuid): RunAgentInput {
  const body = envelope(threadId, newId);
  body.messages = [{ id: newId(), role: "user", content: message }];
  return body;
}

/** ASI09: a resume answers every interrupt of one RUN_FINISHED in one request, with a yes/no decision only. */
export function resumeBody(threadId: string, decisions: readonly Decision[], newId: NewId = uuid): RunAgentInput {
  const body = envelope(threadId, newId);
  body.resume = decisions.map(
    (d): ResumeEntry => ({ interruptId: d.interruptId, status: "resolved", payload: { accepted: d.accepted } }),
  );
  return body;
}

export class SseParseError extends Error {}

/**
 * Incremental SSE parser: frames end at a blank line, `data:` lines join with "\n", `:` comments (keepalives) and
 * other fields are ignored, and a trailing frame without a blank line is emitted by flush().
 */
export class SseParser {
  private buffer = "";
  private data: string[] = [];

  push(chunk: string): AgUiEvent[] {
    this.buffer += chunk;
    const events: AgUiEvent[] = [];
    let newline = this.buffer.indexOf("\n");
    while (newline >= 0) {
      const line = this.buffer.slice(0, newline).replace(/\r$/, "");
      this.buffer = this.buffer.slice(newline + 1);
      this.line(line, events);
      newline = this.buffer.indexOf("\n");
    }
    return events;
  }

  flush(): AgUiEvent[] {
    const events: AgUiEvent[] = [];
    if (this.buffer) {
      this.line(this.buffer.replace(/\r$/, ""), events);
      this.buffer = "";
    }
    this.emit(events);
    return events;
  }

  private line(line: string, events: AgUiEvent[]): void {
    if (line === "") {
      this.emit(events);
    } else if (line.startsWith("data:")) {
      this.data.push(line.slice(5).trimStart());
    }
  }

  private emit(events: AgUiEvent[]): void {
    if (this.data.length === 0) return;
    const raw = this.data.join("\n");
    this.data = [];
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      throw new SseParseError("the server sent an event that is not JSON");
    }
    if (typeof parsed !== "object" || parsed === null || typeof (parsed as { type?: unknown }).type !== "string") {
      throw new SseParseError("the server sent an event without a type");
    }
    events.push(parsed as AgUiEvent);
  }
}

export type StreamOutcome =
  | { kind: "done" }
  | { kind: "http"; status: number; body: string }
  | { kind: "timeout" }
  | { kind: "network"; message: string };

export interface StreamOptions {
  url: string;
  token: string;
  body: RunAgentInput;
  onEvent: (event: AgUiEvent) => void;
  fetchImpl?: typeof fetch;
  idleMs?: number;
  signal?: AbortSignal;
}

/**
 * POSTs one run and feeds its events to onEvent. Non-2xx responses are returned with their status and a short body,
 * never parsed as events. The bearer goes only to `url`, which callers take from the validated runtime config.
 */
export async function streamRun(options: StreamOptions): Promise<StreamOutcome> {
  const { url, token, body, onEvent, fetchImpl = fetch, idleMs = IDLE_TIMEOUT_MS, signal } = options;
  const controller = new AbortController();
  let timedOut = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const resetIdle = (): void => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, idleMs);
  };
  const onCallerAbort = (): void => controller.abort();
  signal?.addEventListener("abort", onCallerAbort, { once: true });

  try {
    resetIdle();
    const response = await fetchImpl(url, {
      method: "POST",
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
      mode: "cors",
      credentials: "omit",
      cache: "no-store",
      referrerPolicy: "no-referrer",
    });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      return { kind: "http", status: response.status, body: text.slice(0, ERROR_BODY_CHARS) };
    }
    if (!response.body) return { kind: "network", message: "the response has no body" };

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const parser = new SseParser();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      resetIdle();
      for (const event of parser.push(decoder.decode(value, { stream: true }))) onEvent(event);
    }
    for (const event of parser.push(decoder.decode())) onEvent(event);
    for (const event of parser.flush()) onEvent(event);
    return { kind: "done" };
  } catch (error) {
    if (timedOut) return { kind: "timeout" };
    if (error instanceof SseParseError) return { kind: "network", message: error.message };
    return { kind: "network", message: error instanceof Error ? error.message : "request failed" };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onCallerAbort);
  }
}
