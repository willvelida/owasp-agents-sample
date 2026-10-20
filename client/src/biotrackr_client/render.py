"""Render an AG-UI event stream to the terminal."""

import json
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.status import Status

RESULT_PREVIEW_CHARS = 600
# AG-UI adds a synthetic tool call for client-side confirmation UIs; the CLI asks in the terminal instead.
SYNTHETIC_TOOLS = {"confirm_changes"}
SLOW_TOOLS = {"generate_report": "generating and reviewing the report..."}


class Renderer:
    def __init__(self, console: Console) -> None:
        self.console = console
        self._args: dict[str, str] = {}
        self._names: dict[str, str] = {}
        self._in_text = False
        self._status: Status | None = None
        self.text: list[str] = []
        self.error: str | None = None
        self.interrupts: list[dict[str, Any]] = []

    def wait(self, message: str) -> None:
        """Show a spinner until the next event arrives (a tool that takes a while, or an approved report)."""
        self._stop_status()
        self._status = self.console.status(f"[dim]{escape(message)}[/]")
        self._status.start()

    def _stop_status(self) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None

    def close(self) -> None:
        self._stop_status()

    def handle(self, event: dict[str, Any]) -> None:
        self._stop_status()
        kind = event.get("type")
        if kind == "TEXT_MESSAGE_CONTENT":
            self._in_text = True
            delta = event.get("delta", "")
            self.text.append(delta)
            self.console.print(delta, end="", markup=False, highlight=False, soft_wrap=True)
        elif kind == "TEXT_MESSAGE_END" and self._in_text:
            self._in_text = False
            self.console.print()
        elif kind == "TOOL_CALL_START":
            self._names[event["toolCallId"]] = event.get("toolCallName", "?")
            self._args[event["toolCallId"]] = ""
        elif kind == "TOOL_CALL_ARGS":
            self._args[event["toolCallId"]] = self._args.get(event["toolCallId"], "") + event.get("delta", "")
        elif kind == "TOOL_CALL_END":
            call_id = event["toolCallId"]
            name, args = self._names.get(call_id, "?"), self._args.get(call_id, "")
            if name in SYNTHETIC_TOOLS:
                return
            self.console.print(f"[bold cyan]> tool[/] [cyan]{escape(name)}[/]([yellow]{escape(args)}[/])")
            if name in SLOW_TOOLS:
                self.wait(SLOW_TOOLS[name])
        elif kind == "TOOL_CALL_RESULT":
            self.console.print(f"[dim]< {escape(_preview(event.get('content', '')))}[/]")
        elif kind == "CUSTOM" and event.get("name") == "function_approval_request":
            call = (event.get("value") or {}).get("function_call") or {}
            self.console.print(f"[bold yellow]? approval needed[/] for [cyan]{escape(str(call.get('name', '?')))}[/]")
        elif kind == "RUN_FINISHED":
            outcome = event.get("outcome") or {}
            self.interrupts = list(outcome.get("interrupts") or []) if outcome.get("type") == "interrupt" else []
        elif kind == "RUN_ERROR":
            # The solution never sends exception text; `code` names the control's exception (MiddlewareFailure).
            code = event.get("code")
            self.error = f"{code}: " if code else ""
            self.error += event.get("message", "unknown error")
            self.console.print(f"[bold red]run error:[/] {escape(self.error)}")


def interrupt_call(interrupt: dict[str, Any]) -> tuple[str, str]:
    """Tool name and arguments an approval interrupt is asking about."""
    meta = ((interrupt.get("metadata") or {}).get("agent_framework") or {}).get("function_call") or {}
    arguments = meta.get("arguments", {})
    return str(meta.get("name", "?")), arguments if isinstance(arguments, str) else json.dumps(arguments)


def _preview(content: str) -> str:
    try:
        payload = json.loads(content)
        if isinstance(payload, dict) and "structuredContent" in payload:
            content = json.dumps(payload["structuredContent"], separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        pass
    return content if len(content) <= RESULT_PREVIEW_CHARS else content[:RESULT_PREVIEW_CHARS] + " ..."
