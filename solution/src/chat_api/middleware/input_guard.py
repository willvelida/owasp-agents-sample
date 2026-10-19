"""Input screening (ASI01): runs before the model, the identity exchange, and any tool call."""

import logging
from collections.abc import Awaitable, Callable

from agent_framework import AgentContext, AgentMiddleware, MiddlewareFailure

from chat_api.middleware.screening import Screener

log = logging.getLogger("chat_api.middleware.input_guard")


class InputGuard(AgentMiddleware):
    """Screens every non-system message in the run input and aborts the run on detection.

    Fail-closed contract: a detection or a screening error raises MiddlewareFailure, so the run ends
    before any context provider, model call, or tool call.
    """

    def __init__(self, screener: Screener) -> None:
        self._screener = screener

    async def process(self, context: AgentContext, call_next: Callable[[], Awaitable[None]]) -> None:
        try:
            for message in context.messages or []:
                if message.role == "system" or not message.text:
                    continue
                verdict = self._screener.screen(message.text, source=f"{message.role} input")
                if verdict.blocked:
                    log.warning("input screening blocked a run: %s", verdict.reason)
                    raise MiddlewareFailure(f"Request blocked by input screening: {verdict.reason}")
        except MiddlewareFailure:
            raise
        except Exception as exc:
            raise MiddlewareFailure("input screening failed; request refused") from exc
        await call_next()
