"""Render an AG-UI event stream to the terminal."""

import json
from typing import Any

from rich.console import Console
from rich.markup import escape

RESULT_PREVIEW_CHARS = 600


class Renderer:
    def __init__(self, console: Console) -> None:
        self.console = console
        self._args: dict[str, str] = {}
        self._names: dict[str, str] = {}
        self._in_text = False
        self.text: list[str] = []
        self.error: str | None = None

    def handle(self, event: dict[str, Any]) -> None:
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
            self.console.print(f"[bold cyan]> tool[/] [cyan]{escape(name)}[/]([yellow]{escape(args)}[/])")
        elif kind == "TOOL_CALL_RESULT":
            self.console.print(f"[dim]< {escape(_preview(event.get('content', '')))}[/]")
        elif kind == "RUN_ERROR":
            # The solution never sends exception text; `code` names the control's exception (MiddlewareFailure).
            code = event.get("code")
            self.error = f"{code}: " if code else ""
            self.error += event.get("message", "unknown error")
            self.console.print(f"[bold red]run error:[/] {escape(self.error)}")


def _preview(content: str) -> str:
    try:
        payload = json.loads(content)
        if isinstance(payload, dict) and "structuredContent" in payload:
            content = json.dumps(payload["structuredContent"], separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        pass
    return content if len(content) <= RESULT_PREVIEW_CHARS else content[:RESULT_PREVIEW_CHARS] + " ..."
