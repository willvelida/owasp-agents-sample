"""Kill switch (ASI10): operators can stop the agent without a redeploy.

Checked at the start of every run and again before every tool call:

* Locally, `AGENT_KILL_SWITCH` in the environment (`on` stops the agent). Compose passes it through; recreate
  chat-api and its sidecar to flip it (solution README, Operations).
* On Azure, the `agent-kill-switch` key in App Configuration, read with the chat-api managed identity
  (App Configuration Data Reader). A successful read is cached for 10 seconds, so a flip takes effect within
  10 seconds and the store sees at most one request per replica per 10 seconds, and only while runs arrive.

Fail closed: an unreachable store (after the cached value expires and one retry), a missing key, an unknown value,
or any error in the check stops the run. The reply is fixed text; no context provider, model, or tool runs.
"""

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from agent_framework import (
    AgentContext,
    AgentMiddleware,
    FunctionInvocationContext,
    FunctionMiddleware,
    MiddlewareFailure,
)

from chat_api.middleware.replies import reply_with

log = logging.getLogger("chat_api.middleware.kill_switch")

ENV_VARIABLE = "AGENT_KILL_SWITCH"
APP_CONFIG_KEY = "agent-kill-switch"
CACHE_SECONDS = 10.0
READ_TIMEOUT_SECONDS = 3.0
READ_ATTEMPTS = 2
SUSPENDED_REPLY = "Biotrackr chat is paused by its operators right now. Your records are safe; please try again later."
_OFF = {"off", "false", "0", "no", "disengaged"}
_ON = {"on", "true", "1", "yes", "engaged"}


def parse(value: str | None) -> bool:
    """True when the agent must stop. Unknown values stop it too (fail closed)."""
    text = (value or "").strip().lower()
    if text in _OFF:
        return False
    if text not in _ON:
        log.warning("kill switch has an unknown value %r; treating it as engaged", text[:20])
    return True


class KillSwitch(Protocol):
    source: str

    async def engaged(self) -> bool: ...


class EnvKillSwitch:
    source = "env"

    def __init__(self, variable: str = ENV_VARIABLE) -> None:
        self._variable = variable

    async def engaged(self) -> bool:
        return parse(os.environ.get(self._variable, "off"))


class AppConfigKillSwitch:
    source = "app-configuration"

    def __init__(
        self,
        endpoint: str,
        *,
        key: str = APP_CONFIG_KEY,
        client: Any = None,
        cache_seconds: float = CACHE_SECONDS,
        timeout: float = READ_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if client is None:
            from azure.appconfiguration.aio import AzureAppConfigurationClient

            from auth_common.azure_credential import azure_credential

            client = AzureAppConfigurationClient(endpoint, azure_credential())
        self._client = client
        self._key = key
        self._cache_seconds = cache_seconds
        self._timeout = timeout
        self._clock = clock
        self._cached: tuple[float, bool] | None = None
        self._lock = asyncio.Lock()

    async def engaged(self) -> bool:
        async with self._lock:
            now = self._clock()
            if self._cached is not None and now - self._cached[0] < self._cache_seconds:
                return self._cached[1]
            try:
                value = await self._read()
            except Exception as exc:
                # Missing key, no permission, timeout, or an unreachable store: stop, and ask again next run.
                log.error("kill switch unreadable (%s); refusing the run", type(exc).__name__)
                self._cached = None
                return True
            self._cached = (now, value)
            return value

    async def _read(self) -> bool:
        # One retry (WI-30): the first read on a new revision can time out while the managed identity token is cold.
        # Only a successful read reaches parse(); two failures raise and the caller refuses the run.
        for attempt in range(READ_ATTEMPTS):
            try:
                setting = await asyncio.wait_for(self._client.get_configuration_setting(key=self._key), self._timeout)
            except Exception as exc:
                if attempt + 1 == READ_ATTEMPTS:
                    raise
                log.warning("kill switch read failed (%s); retrying once", type(exc).__name__)
                continue
            return parse(setting.value)
        raise RuntimeError("unreachable")


def from_environment() -> KillSwitch:
    endpoint = os.environ.get("APP_CONFIG_ENDPOINT", "").strip()
    return AppConfigKillSwitch(endpoint) if endpoint else EnvKillSwitch()


async def _is_engaged(switch: KillSwitch) -> bool:
    try:
        return await switch.engaged()
    except Exception as exc:
        log.error("kill switch check failed (%s); refusing", type(exc).__name__)
        return True


class KillSwitchGuard(AgentMiddleware):
    """Outermost control after the audit trail: a stopped agent never reaches input screening or the model."""

    def __init__(self, switch: KillSwitch, *, audit: Any = None, agent_id: str = "chat-agent") -> None:
        self.switch = switch
        self._audit = audit
        self._agent_id = agent_id

    async def process(self, context: AgentContext, call_next: Callable[[], Awaitable[None]]) -> None:
        if await _is_engaged(self.switch):
            log.warning("kill switch engaged (%s); run refused", self.switch.source)
            if self._audit is not None:
                self._audit.log(
                    event_type="kill_switch",
                    agent_did=self._agent_id,
                    action="refuse_run",
                    data={"source": self.switch.source},
                    outcome="denied",
                )
            reply_with(context, SUSPENDED_REPLY)
            return
        await call_next()


class KillSwitchToolGuard(FunctionMiddleware):
    """A switch flipped mid-run stops the next tool call and aborts the batch."""

    def __init__(self, switch: KillSwitch) -> None:
        self.switch = switch

    async def process(self, context: FunctionInvocationContext, call_next: Callable[[], Awaitable[None]]) -> None:
        if await _is_engaged(self.switch):
            raise MiddlewareFailure("Kill switch engaged: tool call refused")
        await call_next()
