"""Rogue agent detection per user (ASI10).

AGT's RogueDetectionMiddleware scores an agent id across every call it sees. With one shared chat agent, a burst
from one user (or a red-team run) quarantined the agent for everyone (WI-14, WI-19). Here each signed-in user gets
an own AGT `RogueAgentDetector` and `RogueDetectionMiddleware` (agent id `<agent>/<oid>`), built directly with a
configured `RogueDetectorConfig`, plus a deterministic burst ceiling across all of that user's conversations.

Either signal quarantines that user's agent for `quarantine_seconds`: tool calls fail closed (MiddlewareFailure
aborts the batch) and new runs get a fixed reply before the model is called. Other users are not affected.

The ceiling sits above the per-conversation tool budget (ASI02), so a single conversation can never trip it; a
user fanning calls out over several conversations, which the budget alone cannot see, does.
"""

import logging
import time
import warnings
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from agent_framework import (
    AgentContext,
    AgentMiddleware,
    FunctionInvocationContext,
    FunctionMiddleware,
    MiddlewareFailure,
    MiddlewareTermination,
)

from chat_api.auth import current_principal
from chat_api.middleware.replies import reply_with

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from agent_os.integrations.maf_adapter import RogueDetectionMiddleware
    from agent_sre.anomaly import RiskLevel, RogueAgentDetector, RogueDetectorConfig

log = logging.getLogger("chat_api.middleware.rogue_guard")

QUARANTINE_REPLY = (
    "Biotrackr has paused your assistant for a few minutes because it made an unusual burst of requests. "
    "Please try again later."
)
_KEEP_ACTIONS = 500
_KEEP_ASSESSMENTS = 100


@dataclass(frozen=True)
class RogueSettings:
    burst_limit: int = 50
    burst_window_seconds: float = 120.0
    quarantine_seconds: float = 300.0
    quarantine_risk_level: str = "critical"
    frequency_window_seconds: float = 60.0
    frequency_min_windows: int = 10
    max_users: int = 10_000

    def detector_config(self) -> RogueDetectorConfig:
        return RogueDetectorConfig(
            frequency_window_seconds=self.frequency_window_seconds,
            frequency_min_windows=self.frequency_min_windows,
            quarantine_risk_level=RiskLevel(self.quarantine_risk_level),
        )


class BoundedRogueAgentDetector(RogueAgentDetector):
    """AGT's detector keeps every action and assessment for the life of the process; keep the recent ones."""

    def record_action(self, agent_id: str, action: str, tool_name: str, timestamp: float | None = None) -> None:
        super().record_action(agent_id, action, tool_name, timestamp)
        actions = self.entropy_scorer._actions.get(agent_id)  # noqa: SLF001
        if actions is not None and len(actions) > _KEEP_ACTIONS:
            del actions[:-_KEEP_ACTIONS]

    def assess(self, agent_id: str, timestamp: float | None = None) -> Any:
        assessment = super().assess(agent_id, timestamp)
        if len(self._assessments) > _KEEP_ASSESSMENTS:
            del self._assessments[:-_KEEP_ASSESSMENTS]
        return assessment


@dataclass
class _User:
    middleware: RogueDetectionMiddleware
    calls: deque[float] = field(default_factory=deque)


class RogueGuard:
    """Per-user detectors and quarantines, shared by the run gate and the per-call middleware."""

    def __init__(
        self,
        settings: RogueSettings,
        *,
        allowed_tools: Iterable[str],
        agent_id: str,
        audit: Any = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._allowed = list(allowed_tools)
        self._agent_id = agent_id
        self.audit = audit
        self._clock = clock
        self._users: OrderedDict[str, _User] = OrderedDict()
        self._quarantined: dict[str, float] = {}

    def user(self, oid: str) -> _User:
        state = self._users.get(oid)
        if state is None:
            middleware = RogueDetectionMiddleware(
                detector=BoundedRogueAgentDetector(self.settings.detector_config()),
                agent_id=f"{self._agent_id}/{oid}",
                capability_profile={"allowed_tools": self._allowed},
                audit_log=self.audit,
            )
            state = self._users[oid] = _User(middleware)
        self._users.move_to_end(oid)
        while len(self._users) > self.settings.max_users:
            self._users.popitem(last=False)
        return state

    def quarantine_remaining(self, oid: str) -> float:
        until = self._quarantined.get(oid)
        if until is None:
            return 0.0
        remaining = until - self._clock()
        if remaining <= 0:
            # Released: start over with a fresh detector and call window, so the burst that caused the quarantine
            # cannot count against the user again. A new burst still trips the ceiling.
            del self._quarantined[oid]
            self._users.pop(oid, None)
            return 0.0
        return remaining

    def quarantine(self, oid: str, reason: str, **data: Any) -> None:
        self._quarantined[oid] = self._clock() + self.settings.quarantine_seconds
        log.warning("rogue detection quarantined the agent for one user (%s)", reason)
        if self.audit is not None:
            self.audit.log(
                event_type="rogue_detection",
                agent_did=f"{self._agent_id}/{oid}",
                action="quarantine",
                data={"oid": oid, "reason": reason, "quarantine_seconds": self.settings.quarantine_seconds, **data},
                outcome="denied",
            )

    def record_call(self, oid: str) -> int:
        """Counts an executed tool call in the user's sliding window and returns the window's count."""
        now = self._clock()
        calls = self.user(oid).calls
        calls.append(now)
        while calls and now - calls[0] > self.settings.burst_window_seconds:
            calls.popleft()
        return len(calls)


class RogueGate(AgentMiddleware):
    """A quarantined user's runs stop before input screening, the model, or any tool."""

    def __init__(self, guard: RogueGuard) -> None:
        self.guard = guard

    async def process(self, context: AgentContext, call_next: Callable[[], Awaitable[None]]) -> None:
        principal = current_principal.get()
        if principal is not None and self.guard.quarantine_remaining(principal.oid) > 0:
            if self.guard.audit is not None:
                self.guard.audit.log(
                    event_type="rogue_detection",
                    agent_did="rogue-gate",
                    action="refuse_run",
                    data={"oid": principal.oid},
                    outcome="denied",
                )
            reply_with(context, QUARANTINE_REPLY)
            return
        await call_next()


class PerUserRogueDetection(FunctionMiddleware):
    def __init__(self, guard: RogueGuard) -> None:
        self.guard = guard

    async def process(self, context: FunctionInvocationContext, call_next: Callable[[], Awaitable[None]]) -> None:
        principal = current_principal.get()
        if principal is None:
            raise MiddlewareFailure("Tool call aborted: no signed-in user for rogue detection")
        oid = principal.oid
        if self.guard.quarantine_remaining(oid) > 0:
            raise MiddlewareFailure("Tool call aborted: the agent is quarantined for this user")
        count = self.guard.record_call(oid)
        if count > self.guard.settings.burst_limit:
            self.guard.quarantine(oid, "burst", calls=count, window_seconds=self.guard.settings.burst_window_seconds)
            raise MiddlewareFailure(
                f"Tool call aborted: {count} tool calls in {self.guard.settings.burst_window_seconds:.0f} s; "
                "the agent is quarantined for this user"
            )
        started = False

        async def tracked_next() -> None:
            nonlocal started
            started = True
            await call_next()

        try:
            await self.guard.user(oid).middleware.process(context, tracked_next)
        except MiddlewareTermination as exc:
            if started:
                raise
            self.guard.quarantine(oid, "agt-rogue-detector")
            raise MiddlewareFailure(
                "Tool call aborted: AGT rogue detection quarantined the agent for this user"
            ) from exc
