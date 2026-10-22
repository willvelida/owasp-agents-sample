// Event reducer: a pure (state, event) => state with parity to client/src/biotrackr_client/render.py Renderer.handle.
// No Vue import, so it is tested without a DOM. Every string here is untrusted data; components render it as text.
import type { AgUiEvent } from "./agui";

// AG-UI adds a synthetic tool call for client-side confirmation UIs; the approval dialog replaces it.
const SYNTHETIC_TOOLS = new Set(["confirm_changes"]);

export type Item =
  | { kind: "user"; id: number; text: string }
  | { kind: "assistant"; id: number; text: string }
  | { kind: "tool-call"; id: number; name: string; args: string }
  | { kind: "tool-result"; id: number; content: string }
  | { kind: "notice"; id: number; text: string }
  | { kind: "run-error"; id: number; text: string }
  | { kind: "http-error"; id: number; status: number; text: string };

export interface PendingApproval {
  interruptId: string;
  name: string;
  /** Pretty-printed JSON when the arguments parse, otherwise the raw text. Never truncated. */
  args: string;
}

export interface ChatState {
  items: readonly Item[];
  pending: readonly PendingApproval[];
  error: string | null;
  nextId: number;
  openText: number | null;
  toolNames: Readonly<Record<string, string>>;
  toolArgs: Readonly<Record<string, string>>;
}

export function initialState(): ChatState {
  return { items: [], pending: [], error: null, nextId: 1, openText: null, toolNames: {}, toolArgs: {} };
}

type NewItem = Item extends infer T ? (T extends Item ? Omit<T, "id"> : never) : never;

function append(state: ChatState, item: NewItem, keepText = false): ChatState {
  return {
    ...state,
    items: [...state.items, { ...item, id: state.nextId } as Item],
    nextId: state.nextId + 1,
    openText: keepText ? state.openText : null,
  };
}

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

/** Like the CLI's _preview, unwraps an MCP result's structuredContent, but never truncates. */
export function resultText(content: unknown): string {
  const text = typeof content === "string" ? content : JSON.stringify(content ?? "");
  try {
    const payload: unknown = JSON.parse(text);
    if (typeof payload === "object" && payload !== null && !Array.isArray(payload) && "structuredContent" in payload) {
      return JSON.stringify((payload as { structuredContent: unknown }).structuredContent);
    }
  } catch {
    // Not JSON: show it as it is.
  }
  return text;
}

function prettyArgs(args: unknown): string {
  if (typeof args !== "string") return JSON.stringify(args ?? {}, null, 2);
  try {
    return JSON.stringify(JSON.parse(args), null, 2);
  } catch {
    return args;
  }
}

/** Tool name and arguments an approval interrupt is asking about (render.py interrupt_call). */
export function interruptCall(interrupt: unknown): { name: string; args: string } {
  const call = record(record(record(record(interrupt).metadata).agent_framework).function_call);
  return { name: str(call.name, "?"), args: prettyArgs(call.arguments) };
}

export function addUserMessage(state: ChatState, text: string): ChatState {
  return append({ ...state, error: null, pending: [] }, { kind: "user", text });
}

export function addNotice(state: ChatState, text: string): ChatState {
  return append(state, { kind: "notice", text });
}

export function addHttpError(state: ChatState, status: number, text: string): ChatState {
  return append({ ...state, error: `HTTP ${status}`, pending: [] }, { kind: "http-error", status, text });
}

export function addRunError(state: ChatState, text: string): ChatState {
  return append({ ...state, error: text, pending: [] }, { kind: "run-error", text });
}

export function reduce(state: ChatState, event: AgUiEvent): ChatState {
  switch (event.type) {
    case "TEXT_MESSAGE_CONTENT": {
      const delta = str(event.delta);
      const open = state.openText === null ? undefined : state.items.find((i) => i.id === state.openText);
      if (open && open.kind === "assistant") {
        const items = state.items.map((i) => (i === open ? { ...open, text: open.text + delta } : i));
        return { ...state, items };
      }
      const next = append(state, { kind: "assistant", text: delta });
      return { ...next, openText: state.nextId };
    }
    case "TEXT_MESSAGE_END":
      return { ...state, openText: null };
    case "TOOL_CALL_START": {
      const id = str(event.toolCallId);
      return {
        ...state,
        toolNames: { ...state.toolNames, [id]: str(event.toolCallName, "?") },
        toolArgs: { ...state.toolArgs, [id]: "" },
      };
    }
    case "TOOL_CALL_ARGS": {
      const id = str(event.toolCallId);
      return { ...state, toolArgs: { ...state.toolArgs, [id]: (state.toolArgs[id] ?? "") + str(event.delta) } };
    }
    case "TOOL_CALL_END": {
      const id = str(event.toolCallId);
      const name = state.toolNames[id] ?? "?";
      if (SYNTHETIC_TOOLS.has(name)) return state;
      return append(state, { kind: "tool-call", name, args: state.toolArgs[id] ?? "" });
    }
    case "TOOL_CALL_RESULT":
      return append(state, { kind: "tool-result", content: resultText(event.content) });
    case "CUSTOM": {
      if (event.name !== "function_approval_request") return state;
      const call = record(record(event.value).function_call);
      return append(state, { kind: "notice", text: `approval needed for ${str(call.name, "?")}` });
    }
    case "RUN_FINISHED": {
      const outcome = record(event.outcome);
      const interrupts = outcome.type === "interrupt" && Array.isArray(outcome.interrupts) ? outcome.interrupts : [];
      const pending = interrupts.map((i): PendingApproval => ({ interruptId: str(record(i).id), ...interruptCall(i) }));
      return { ...state, openText: null, pending };
    }
    case "RUN_ERROR": {
      // The solution never sends exception text; `code` names the control's exception.
      const code = str(event.code);
      const text = (code ? `${code}: ` : "") + str(event.message, "unknown error");
      return append({ ...state, error: text, pending: [] }, { kind: "run-error", text });
    }
    default:
      return state;
  }
}
