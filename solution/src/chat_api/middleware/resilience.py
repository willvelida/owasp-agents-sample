"""Resilience for the chat agent's dependencies (ASI08).

* Timeouts: every HTTP dependency uses connect 5 s and read 30 s (`HTTP_TIMEOUT`), including the MCP client's own
  HTTP client and its session request timeout, so a hung server cannot hold a run indefinitely.
* Retries: at most 2, with full jitter, only when the dependency could not be reached at all (never after a
  timeout on a hung dependency, never for policy or security failures, and never for report submissions).
* Circuit breakers: one for the health MCP server and one for the report agent. After 3 consecutive failures the
  breaker opens and calls fail fast for 30 seconds; then one trial call decides whether it closes again.
* Graceful degradation: when a dependency is unavailable the user gets a short "try again" reply, which still
  passes through the output guard, instead of a generic RUN_ERROR.
* Bounded runs: the model client has the same timeouts and 2 retries, the tool loop at most 8 model round trips
  and 120 seconds, replies at most `max_output_tokens`, and each conversation a token budget.

Security failures (input screening, tool policy, descriptor pins, identity) are never degraded or retried; they
still fail closed with MiddlewareFailure or their own error.
"""

import asyncio
import logging
import random
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any

import httpx
from agent_framework import (
    AgentContext,
    AgentMiddleware,
    AgentResponse,
    AgentResponseUpdate,
    ChatContext,
    ChatMiddleware,
    ChatResponse,
    Content,
    Message,
    MiddlewareException,
    MiddlewareFailure,
    ResponseStream,
)
from agent_framework.exceptions import ToolExecutionException

from chat_api.auth import current_principal
from chat_api.mcp_pinning import DescriptorPinError, PinnedMCPStreamableHTTPTool
from chat_api.middleware.replies import reply_with, response_for
from chat_api.session_store import TokenBudget

log = logging.getLogger("chat_api.middleware.resilience")

HTTP_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
MAX_RETRIES = 2
MAX_MODEL_ROUND_TRIPS = 8
MAX_RUN_TOOL_SECONDS = 120.0

DEGRADED_REPLY = (
    "I can't reach the service that holds your health records right now, so I can't answer that at the moment. "
    "Your records are safe; please try again in a minute."
)
TOKEN_BUDGET_REPLY = "This conversation has reached its usage limit. Please start a new conversation to keep going."  # noqa: S105


class DependencyUnavailable(RuntimeError):
    """An availability failure of a dependency: degrade, never a reason to relax a control."""

    def __init__(self, dependency: str, message: str | None = None) -> None:
        super().__init__(message or f"{dependency} is unavailable")
        self.dependency = dependency


class CircuitOpenError(DependencyUnavailable):
    pass


def _chain(exc: BaseException) -> Iterable[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__
    inner = getattr(exc, "inner_exception", None)
    if isinstance(inner, BaseException) and id(inner) not in seen:
        yield from _chain(inner)
    if isinstance(exc, BaseExceptionGroup):
        for member in exc.exceptions:
            yield from _chain(member)


def _security_failure(exc: BaseException) -> bool:
    from chat_api.identity import IdentityError

    return any(
        isinstance(e, MiddlewareException | PermissionError | DescriptorPinError | IdentityError) for e in _chain(exc)
    )


def is_transient(exc: BaseException) -> bool:
    """A transport-level failure or timeout: a strike against the circuit breaker."""
    if _security_failure(exc):
        return False
    import anyio

    transient: tuple[type[BaseException], ...] = (
        httpx.TransportError,
        TimeoutError,
        ConnectionError,
        OSError,
        anyio.ClosedResourceError,
        anyio.BrokenResourceError,
        DependencyUnavailable,
    )
    # The MCP session reports its own request timeout as McpError 408.
    if any(
        type(e).__name__ == "McpError" and getattr(getattr(e, "error", None), "code", None) == 408 for e in _chain(exc)
    ):
        return True
    return any(isinstance(e, transient) for e in _chain(exc))


def is_connect_failure(exc: BaseException) -> bool:
    """Could not reach the dependency at all: worth a retry. A timeout on a hung dependency is not retried."""
    if _security_failure(exc) or isinstance(exc, CircuitOpenError):
        return False
    import socket

    import anyio

    unreachable: tuple[type[BaseException], ...] = (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        ConnectionRefusedError,
        ConnectionResetError,
        socket.gaierror,
        anyio.ClosedResourceError,
        anyio.BrokenResourceError,
    )
    return any(isinstance(e, unreachable) for e in _chain(exc))


def degradable(exc: BaseException) -> bool:
    """True when the run failed because a dependency is unavailable (and not because a control refused it)."""
    if _security_failure(exc):
        return False
    import openai

    unavailable: tuple[type[BaseException], ...] = (
        DependencyUnavailable,
        openai.APIConnectionError,
        openai.APITimeoutError,
        openai.InternalServerError,
        openai.RateLimitError,
    )
    return any(isinstance(e, unavailable) for e in _chain(exc)) or is_transient(exc)


async def retry(
    operation: Callable[[], Awaitable[Any]],
    *,
    retries: int = MAX_RETRIES,
    should_retry: Callable[[BaseException], bool] = is_connect_failure,
    base_delay: float = 0.25,
    max_delay: float = 2.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Any:
    """At most `retries` retries with full jitter (a random delay up to base * 2^attempt, capped)."""
    for attempt in range(retries + 1):
        try:
            return await operation()
        except Exception as exc:
            if attempt >= retries or not should_retry(exc):
                raise
            await sleep(random.uniform(0, min(max_delay, base_delay * 2**attempt)))  # noqa: S311
    raise AssertionError("unreachable")


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 3,
        reset_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        audit: Any = None,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._clock = clock
        self._audit = audit
        self._failures = 0
        self._opened_at: float | None = None
        self._trial_in_flight = False

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self.reset_seconds:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        state = self.state
        if state == "closed":
            return True
        if state == "half_open" and not self._trial_in_flight:
            self._trial_in_flight = True
            return True
        return False

    def record_success(self) -> None:
        if self._opened_at is not None:
            log.info("circuit %s closed", self.name)
            self._log("close", "success")
        self._failures = 0
        self._opened_at = None
        self._trial_in_flight = False

    def record_failure(self) -> None:
        self._failures += 1
        was_trial = self._trial_in_flight
        self._trial_in_flight = False
        if was_trial or self._failures >= self.failure_threshold:
            if self._opened_at is None or was_trial:
                log.warning("circuit %s opened after %d failures", self.name, self._failures)
                self._log("open", "failure")
            self._opened_at = self._clock()

    def release(self) -> None:
        """Ends a trial call whose outcome says nothing about availability (for example a policy failure)."""
        self._trial_in_flight = False

    def _log(self, action: str, outcome: str) -> None:
        if self._audit is not None:
            self._audit.log(
                event_type="circuit_breaker",
                agent_did=f"breaker/{self.name}",
                action=action,
                data={"dependency": self.name, "failures": self._failures},
                outcome=outcome,
            )

    async def call(self, operation: Callable[[], Awaitable[Any]], *, counts: Callable[[BaseException], bool]) -> Any:
        """Runs `operation` if the circuit allows it; failures for which `counts` is true are strikes."""
        if not self.allow():
            raise CircuitOpenError(self.name, f"{self.name} is temporarily unavailable (circuit open)")
        try:
            result = await operation()
        except Exception as exc:
            if counts(exc):
                self.record_failure()
            else:
                self.release()  # it answered, or never got that far: not a verdict on availability
            raise
        except BaseException:
            self.release()
            raise
        self.record_success()
        return result


class ResilientMCPStreamableHTTPTool(PinnedMCPStreamableHTTPTool):
    """The pinned health MCP tool with transport timeouts, jittered connect retries, and a circuit breaker.

    MAF serialises the calls of one MCP tool behind a lock and runs its connection lifecycle on an owner task, so
    deadlines are enforced by the HTTP client (connect 5 s, read 30 s) and the MCP session's request timeout, never by
    cancelling MAF's own operations: a cancelled call can leave the session wedged, and a deadline around a queued
    call measures the queue, not the server. A connection failure becomes DependencyUnavailable (the run degrades);
    a descriptor pin mismatch is never retried or degraded. With the circuit open, connects and calls fail fast.
    """

    def __init__(self, *args: Any, breaker: CircuitBreaker, **kwargs: Any) -> None:
        kwargs.setdefault("request_timeout", int(HTTP_TIMEOUT.read or 30))
        if kwargs.get("http_client") is None:
            # MAF's own client allows 300 s reads on the event stream. Same redirect and cookie policy otherwise.
            kwargs["http_client"] = httpx.AsyncClient(
                follow_redirects=True,
                timeout=HTTP_TIMEOUT,
                cookies=CookieJar(policy=DefaultCookiePolicy(allowed_domains=[])),
            )
        super().__init__(*args, **kwargs)
        self.breaker = breaker

    async def connect(self, *, reset: bool = False) -> None:
        parent_connect = super().connect

        def unavailable(exc: BaseException) -> bool:
            # MAF reports a refused or dropped connection as a bare ToolException (cause: an anyio cancellation),
            # so any connect failure that is not a control refusal counts as the server being unavailable.
            return not _security_failure(exc) and not isinstance(exc, CircuitOpenError)

        try:
            await self.breaker.call(
                lambda: retry(lambda: parent_connect(reset=reset), should_retry=unavailable),
                counts=lambda exc: not _security_failure(exc),
            )
        except Exception as exc:
            if _security_failure(exc):
                raise
            raise DependencyUnavailable("health-mcp", "the health records service is unavailable") from exc

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        parent_call = super().call_tool
        try:
            # MAF already reconnects and retries once when the session is lost; no second retry layer here.
            return await self.breaker.call(lambda: parent_call(tool_name, **kwargs), counts=is_transient)
        except CircuitOpenError as exc:
            raise ToolExecutionException("The health records service is temporarily unavailable.") from exc


class GracefulDegradation(AgentMiddleware):
    """Replaces a run that failed because a dependency is down with a short reply that passes the output guard.

    Controls that refuse a run (MiddlewareFailure, identity, descriptor pins) are re-raised unchanged.
    """

    def __init__(self, output_guard: Any = None, *, audit: Any = None) -> None:
        self._output_guard = output_guard
        self._audit = audit

    async def _reply_text(self, context: AgentContext, exc: BaseException) -> str:
        dependency = next((e.dependency for e in _chain(exc) if isinstance(e, DependencyUnavailable)), "model")
        log.warning("run degraded: %s unavailable (%s)", dependency, type(exc).__name__)
        if self._audit is not None:
            self._audit.log(
                event_type="resilience",
                agent_did="graceful-degradation",
                action="degraded_reply",
                data={"dependency": dependency, "error": type(exc).__name__},
                outcome="failure",
            )
        if self._output_guard is None:
            return DEGRADED_REPLY
        question = next((m.text for m in reversed(list(context.messages or [])) if m.role == "user" and m.text), "")
        guarded = await self._output_guard.guard(
            ChatResponse(messages=[Message(role="assistant", contents=[Content.from_text(DEGRADED_REPLY)])]),
            question,
        )
        return guarded.text or DEGRADED_REPLY

    async def process(self, context: AgentContext, call_next: Callable[[], Awaitable[None]]) -> None:
        try:
            await call_next()
        except Exception as exc:
            if not degradable(exc):
                raise
            reply_with(context, await self._reply_text(context, exc))
            return
        if context.stream and isinstance(context.result, ResponseStream):
            context.result = self._wrap(context, context.result)

    def _wrap(self, context: AgentContext, inner: ResponseStream) -> ResponseStream:
        degraded: list[str] = []

        async def updates() -> AsyncIterator[AgentResponseUpdate]:
            try:
                async for update in inner:
                    yield update
            except Exception as exc:
                if not degradable(exc):
                    raise
                text = await self._reply_text(context, exc)
                degraded.append(text)
                yield AgentResponseUpdate(
                    role="assistant", contents=[Content.from_text(text)], message_id=str(uuid.uuid4())
                )

        async def finalize(_: Any) -> AgentResponse:
            if degraded:
                return response_for(degraded[0])
            return await inner.get_final_response()

        return ResponseStream(updates(), finalizer=finalize)


def _session_key(session: Any) -> tuple[str, str] | None:
    principal = current_principal.get()
    session_id = getattr(session, "session_id", None)
    if principal is None or not session_id:
        return None
    return principal.oid, str(session_id)


class TokenBudgetGate(AgentMiddleware):
    """A conversation that spent its token budget gets a fixed reply before the model is called."""

    def __init__(self, budget: TokenBudget, *, audit: Any = None) -> None:
        self.budget = budget
        self._audit = audit

    async def process(self, context: AgentContext, call_next: Callable[[], Awaitable[None]]) -> None:
        key = _session_key(context.session)
        if key is not None and self.budget.exhausted(*key):
            if self._audit is not None:
                self._audit.log(
                    event_type="token_budget",
                    agent_did="token-budget",
                    action="refuse_run",
                    data={"limit": self.budget.limit, "tokens": self.budget.used(*key)},
                    outcome="denied",
                )
            reply_with(context, TOKEN_BUDGET_REPLY)
            return
        await call_next()


def _estimate_tokens(messages: Iterable[Message], response: ChatResponse | None) -> int:
    characters = sum(len(m.text or "") for m in messages)
    if response is not None:
        characters += len(response.text or "")
    return max(1, characters // 4)


def _tokens_of(messages: Iterable[Message], response: ChatResponse | None) -> int:
    usage = getattr(response, "usage_details", None) or {}
    total = usage.get("total_token_count") or (
        (usage.get("input_token_count") or 0) + (usage.get("output_token_count") or 0)
    )
    return int(total) if total else _estimate_tokens(messages, response)


class TokenAccounting(ChatMiddleware):
    """Counts every model call against the conversation's budget and stops a run that would go over it."""

    def __init__(self, budget: TokenBudget) -> None:
        self.budget = budget

    async def process(self, context: ChatContext, call_next: Callable[[], Awaitable[None]]) -> None:
        key = _session_key(context.session)
        if key is not None and self.budget.exhausted(*key):
            raise MiddlewareFailure("Token budget exhausted for this conversation")
        messages = list(context.messages)
        await call_next()
        if key is None:
            return
        if context.stream:

            def account(response: ChatResponse) -> None:
                self.budget.add(*key, _tokens_of(messages, response))

            context.stream_result_hooks.append(account)
        else:
            self.budget.add(*key, _tokens_of(messages, context.result))


def harden_model_client(client: Any) -> Any:
    """Timeouts and bounded retries on the OpenAI client inside a MAF chat client, and a bounded tool loop."""
    inner = getattr(client, "client", None)
    if inner is not None and hasattr(inner, "with_options"):
        # The OpenAI SDK retries with exponential backoff and jitter.
        client.client = inner.with_options(timeout=HTTP_TIMEOUT, max_retries=MAX_RETRIES)
    config = getattr(client, "function_invocation_configuration", None)
    if isinstance(config, dict):
        config.update(
            max_iterations=MAX_MODEL_ROUND_TRIPS,
            max_duration_seconds=MAX_RUN_TOOL_SECONDS,
            max_consecutive_errors_per_request=2,
        )
    return client
