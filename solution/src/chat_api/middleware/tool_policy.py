"""Tool governance (ASI02): allowlist, deny patterns, and the per-conversation call budget.

OQ-12 (verified against MAF 1.22.0): MiddlewareTermination raised by one call in a parallel batch
stops only that call; its siblings still run. MiddlewareFailure cancels the in-flight batch and aborts
the run. ToolBatchGuard is therefore a chat middleware: it inspects the whole batch the model asked
for and raises MiddlewareFailure before any call in it starts. FailClosed and ToolCallGuard repeat
the check per call as defence in depth.
"""

import fnmatch
import json
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

from agent_framework import (
    ChatContext,
    ChatMiddleware,
    ChatResponse,
    FunctionInvocationContext,
    FunctionMiddleware,
    MiddlewareFailure,
    MiddlewareTermination,
)

from chat_api.auth import current_principal
from chat_api.session_store import ToolBudget

log = logging.getLogger("chat_api.middleware.tool_policy")


class ToolRules:
    def __init__(self, allowed: Iterable[str], denied_patterns: Iterable[str], max_page_size: int = 50) -> None:
        self.allowed = frozenset(allowed)
        self.denied_patterns = tuple(denied_patterns)
        self.max_page_size = max_page_size

    def violation(self, name: str | None, arguments: Any = None) -> str | None:
        if not name:
            return "unnamed tool call"
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in self.denied_patterns):
            return f"tool '{name}' is denied by policy"
        if name not in self.allowed:
            return f"tool '{name}' is not on the allowlist"
        try:
            args = _arguments(arguments)
            page_size = int(args.get("page_size", 1))
        except (TypeError, ValueError):
            return f"tool '{name}' has unreadable arguments"
        if page_size > self.max_page_size:
            return f"tool '{name}' asked for page_size {page_size}; the policy maximum is {self.max_page_size}"
        return None


def _arguments(arguments: Any) -> Mapping[str, Any]:
    if arguments is None or arguments == "":
        return {}
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    if hasattr(arguments, "model_dump"):
        arguments = arguments.model_dump()
    if not isinstance(arguments, Mapping):
        raise TypeError("arguments must be an object")
    return arguments


def _function_calls(response: ChatResponse) -> list[Any]:
    return [c for m in response.messages for c in m.contents if c.type == "function_call"]


class ToolBatchGuard(ChatMiddleware):
    """Checks every model response before its tool calls run; one bad call aborts the whole batch."""

    def __init__(self, rules: ToolRules, budget: ToolBudget) -> None:
        self._rules = rules
        self._budget = budget

    async def process(self, context: ChatContext, call_next: Callable[[], Awaitable[None]]) -> None:
        await call_next()

        async def gate(response: ChatResponse) -> None:
            await self._check(context, response)

        if context.stream:
            # Buffer the model's updates so a denied batch never reaches the client either.
            context.stream_buffer_updates = True
            context.stream_result_gates_before.append(gate)
        elif context.result is not None:
            await gate(context.result)

    async def _check(self, context: ChatContext, response: ChatResponse) -> None:
        calls = _function_calls(response)
        if not calls:
            return
        for call in calls:
            if reason := self._rules.violation(call.name, call.arguments):
                log.warning("tool batch aborted: %s", reason)
                raise MiddlewareFailure(f"Tool batch aborted: {reason}")
        principal = current_principal.get()
        session_id = context.session.session_id if context.session else None
        if principal is None or not session_id:
            raise MiddlewareFailure("Tool batch aborted: no signed-in user or session for the tool budget")
        per_tool = Counter(str(call.name) for call in calls)
        if not await self._budget.reserve(principal.oid, session_id, len(calls), per_tool):
            limited = {n: self._budget.tool_limits[n] for n in per_tool if n in self._budget.tool_limits}
            log.warning("tool batch aborted: budget of %d calls (per-tool %s) exceeded", self._budget.limit, limited)
            raise MiddlewareFailure(
                f"Tool batch aborted: this conversation has reached its limit of {self._budget.limit} tool calls"
                + "".join(f" or {limit} {name} calls" for name, limit in limited.items())
            )


class ToolCallGuard(FunctionMiddleware):
    """Per-call allowlist and deny-pattern check, raising MiddlewareFailure (never fail-open)."""

    def __init__(self, rules: ToolRules) -> None:
        self._rules = rules

    async def process(self, context: FunctionInvocationContext, call_next: Callable[[], Awaitable[None]]) -> None:
        if reason := self._rules.violation(context.function.name, context.arguments):
            raise MiddlewareFailure(f"Tool call aborted: {reason}")
        await call_next()


class FailClosed(FunctionMiddleware):
    """Adapts AGT function middleware to the fail-closed contract.

    AGT's CapabilityGuardMiddleware and RogueDetectionMiddleware deny with MiddlewareTermination, which
    lets sibling calls run, and an ordinary exception from a guard would fail open. Both become
    MiddlewareFailure here. Errors raised by the tool itself, after the guard let it through, pass
    unchanged so MAF reports them to the model as tool errors.
    """

    def __init__(self, inner: FunctionMiddleware) -> None:
        self.inner = inner

    async def process(self, context: FunctionInvocationContext, call_next: Callable[[], Awaitable[None]]) -> None:
        started = False

        async def tracked_next() -> None:
            nonlocal started
            started = True
            await call_next()

        try:
            await self.inner.process(context, tracked_next)
        except MiddlewareFailure:
            raise
        except MiddlewareTermination as exc:
            raise MiddlewareFailure(f"{type(self.inner).__name__}: {exc}") from exc
        except Exception as exc:
            if started:
                raise
            raise MiddlewareFailure(f"{type(self.inner).__name__} failed; tool call refused") from exc
