"""Tool result screening (ASI01 indirect injection, ADR-0020)."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from agent_framework import Content, FunctionInvocationContext, FunctionMiddleware, MiddlewareFailure

from chat_api.middleware.screening import Screener

log = logging.getLogger("chat_api.middleware.tool_result_guard")


class ToolResultGuard(FunctionMiddleware):
    """Screens every tool result before the model sees it.

    A detection aborts the run with MiddlewareFailure: the result never reaches the model and no
    further tool call starts. Clean results are wrapped in an <untrusted-data> envelope that the
    system prompt tells the model to treat as data, never as instructions.
    """

    def __init__(self, screener: Screener) -> None:
        self._screener = screener

    async def process(self, context: FunctionInvocationContext, call_next: Callable[[], Awaitable[None]]) -> None:
        await call_next()
        name = context.function.name
        try:
            text = _result_text(context.result)
            verdict = self._screener.screen(text, source=f"tool result from {name}")
        except Exception as exc:
            raise MiddlewareFailure(f"tool result screening failed for {name}; run aborted") from exc
        if verdict.blocked:
            log.warning("tool result guard aborted a run: %s", verdict.reason)
            raise MiddlewareFailure(f"Run aborted by tool result screening: {verdict.reason}")
        safe = text.replace("</untrusted-data", "&lt;/untrusted-data")
        context.result = [Content.from_text(f'<untrusted-data tool="{name}">\n{safe}\n</untrusted-data>')]


def _result_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        parts = []
        for item in result:
            if isinstance(item, Content):
                if item.type != "text":
                    raise ValueError(f"unexpected {item.type} content in a tool result")
                parts.append(item.text or "")
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(result)
