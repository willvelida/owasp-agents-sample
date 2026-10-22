import { describe, expect, it } from "vitest";
import type { AgUiEvent } from "../src/agui";
import { initialState, reduce, resultText, type ChatState } from "../src/events";

function run(events: AgUiEvent[], state: ChatState = initialState()): ChatState {
  return events.reduce(reduce, state);
}

const approvalInterrupt = (id: string, name: string, args: unknown) => ({
  id,
  reason: "tool_approval",
  metadata: { agent_framework: { function_call: { name, arguments: args } } },
});

describe("reduce", () => {
  it("appends text deltas to one assistant item until the message ends", () => {
    const state = run([
      { type: "TEXT_MESSAGE_START", messageId: "m1" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "Hello" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: ", alice" },
      { type: "TEXT_MESSAGE_END", messageId: "m1" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: "m2", delta: "Second" },
    ]);
    expect(state.items.map((i) => (i.kind === "assistant" ? i.text : i.kind))).toEqual(["Hello, alice", "Second"]);
  });

  it("shows a tool call at TOOL_CALL_END with its accumulated arguments", () => {
    const state = run([
      { type: "TOOL_CALL_START", toolCallId: "c1", toolCallName: "get_sleep_by_date" },
      { type: "TOOL_CALL_ARGS", toolCallId: "c1", delta: '{"date":' },
      { type: "TOOL_CALL_ARGS", toolCallId: "c1", delta: '"2026-10-19"}' },
    ]);
    expect(state.items).toEqual([]);
    const ended = reduce(state, { type: "TOOL_CALL_END", toolCallId: "c1" });
    expect(ended.items).toEqual([{ kind: "tool-call", id: 1, name: "get_sleep_by_date", args: '{"date":"2026-10-19"}' }]);
  });

  it("hides the synthetic confirm_changes call", () => {
    const state = run([
      { type: "TOOL_CALL_START", toolCallId: "c9", toolCallName: "confirm_changes" },
      { type: "TOOL_CALL_ARGS", toolCallId: "c9", delta: "{}" },
      { type: "TOOL_CALL_END", toolCallId: "c9" },
    ]);
    expect(state.items).toEqual([]);
  });

  it("shows the full, untruncated tool result with structuredContent unwrapped", () => {
    const notes = "x".repeat(5000);
    const content = JSON.stringify({ content: [{ type: "text", text: "ignored" }], structuredContent: { items: [{ notes }] } });
    const state = reduce(initialState(), { type: "TOOL_CALL_RESULT", toolCallId: "c1", content });
    const item = state.items[0];
    expect(item?.kind).toBe("tool-result");
    if (item?.kind === "tool-result") expect(item.content).toBe(JSON.stringify({ items: [{ notes }] }));
    expect(resultText("not json <b>")).toBe("not json <b>");
  });

  it("turns a CUSTOM approval request into a notice only", () => {
    const state = reduce(initialState(), {
      type: "CUSTOM",
      name: "function_approval_request",
      value: { function_call: { name: "generate_report", arguments: { kind: "sleep" } } },
    });
    expect(state.items).toEqual([{ kind: "notice", id: 1, text: "approval needed for generate_report" }]);
    expect(state.pending).toEqual([]);
  });

  it("ignores other CUSTOM events", () => {
    expect(reduce(initialState(), { type: "CUSTOM", name: "other", value: {} }).items).toEqual([]);
  });

  it("turns RUN_FINISHED interrupts into pending decisions with pretty-printed arguments", () => {
    const state = reduce(initialState(), {
      type: "RUN_FINISHED",
      outcome: {
        type: "interrupt",
        interrupts: [
          approvalInterrupt("int-a", "generate_report", '{"kind":"sleep","days":7}'),
          approvalInterrupt("int-b", "delete_entry", { id: "x" }),
        ],
      },
    });
    expect(state.pending).toEqual([
      { interruptId: "int-a", name: "generate_report", args: '{\n  "kind": "sleep",\n  "days": 7\n}' },
      { interruptId: "int-b", name: "delete_entry", args: '{\n  "id": "x"\n}' },
    ]);
  });

  it("clears pending decisions on a RUN_FINISHED without interrupts", () => {
    const pending = reduce(initialState(), {
      type: "RUN_FINISHED",
      outcome: { type: "interrupt", interrupts: [approvalInterrupt("i", "t", "{}")] },
    });
    expect(reduce(pending, { type: "RUN_FINISHED", outcome: { type: "success" } }).pending).toEqual([]);
  });

  it("shows RUN_ERROR as code: message", () => {
    const state = reduce(initialState(), { type: "RUN_ERROR", code: "MiddlewareFailure", message: "blocked by policy" });
    expect(state.error).toBe("MiddlewareFailure: blocked by policy");
    expect(state.items).toEqual([{ kind: "run-error", id: 1, text: "MiddlewareFailure: blocked by policy" }]);
  });

  it("treats an operational refusal as plain assistant text, not an error", () => {
    const state = reduce(initialState(), { type: "TEXT_MESSAGE_CONTENT", delta: "The assistant is paused by an operator." });
    expect(state.error).toBeNull();
    expect(state.items[0]?.kind).toBe("assistant");
  });

  it("does not mutate the previous state", () => {
    const before = initialState();
    const frozen = JSON.stringify(before);
    reduce(before, { type: "TEXT_MESSAGE_CONTENT", delta: "x" });
    expect(JSON.stringify(before)).toBe(frozen);
  });
});
