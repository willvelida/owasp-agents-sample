"""ASI08 bulkhead: one health MCP session per signed-in user.

MAF serialises every call on an MCP tool instance behind one lock and reconnects the session whenever the per-call
headers change. With one shared instance, each switch between users' OBO tokens reconnected the session under that
lock, and one stalled reconnect stopped every user's tool calls (seen in the S4 red team: alice's run, then bob's burst,
then nothing for three minutes). Here each user has their own tool and session: one user's burst or stall cannot hold
another user's calls. The circuit breaker stays shared, because it describes the server, not the user.

A user's tool is bound to that user. A refreshed token for the same user replaces the session's headers without a
reconnect (health-mcp is stateless and checks the token on every request); a different user fails closed.
"""

import asyncio
import contextvars
import logging
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from chat_api.auth import current_principal
from chat_api.identity import IdentityError
from chat_api.middleware.resilience import ResilientMCPStreamableHTTPTool

log = logging.getLogger("chat_api.mcp_pool")

current_user_mcp_tool: contextvars.ContextVar["UserMCPTool | None"] = contextvars.ContextVar(
    "current_user_mcp_tool", default=None
)


class UserMCPTool(ResilientMCPStreamableHTTPTool):
    """The health MCP tool of one signed-in user."""

    def __init__(self, *args: Any, owner: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.owner = owner

    async def _ensure_session_identity(self, headers: Mapping[str, str], kwargs: Mapping[str, Any]) -> None:
        principal = current_principal.get()
        if principal is None or principal.oid != self.owner:
            raise IdentityError("the health tool belongs to another user")
        if self.is_connected and self._session_header_identity is not None:
            self._bind_session_headers(headers)  # same user, refreshed token: no reconnect
            return
        await super()._ensure_session_identity(headers, kwargs)


class UserMCPTools:
    """Per-user MCP tools, at most `max_users` (least recently used first out, closed after a grace period)."""

    def __init__(
        self,
        factory: Callable[[str], UserMCPTool],
        *,
        function_names: Iterable[str],
        max_users: int = 256,
        close_after_seconds: float = 300.0,
    ) -> None:
        self._factory = factory
        self.function_names = frozenset(function_names)
        self.max_users = max_users
        self.close_after_seconds = close_after_seconds
        self._tools: OrderedDict[str, UserMCPTool] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}
        self._closing: set[asyncio.Task[None]] = set()

    def __len__(self) -> int:
        return len(self._tools)

    async def acquire(self, oid: str) -> UserMCPTool:
        """Connects (once) and returns the user's tool, and makes it this run's MCP tool."""
        lock = self._locks.setdefault(oid, asyncio.Lock())
        async with lock:
            tool = self._tools.get(oid)
            if tool is None:
                tool = self._tools[oid] = self._factory(oid)
            self._tools.move_to_end(oid)
            # As MAF's Agent does for its own MCP tools: bind headers, connect if needed, bind again.
            await tool._prepare_for_run({})  # noqa: SLF001
            if not tool.is_connected:
                await tool.connect()
                await tool._prepare_for_run({})  # noqa: SLF001
        self._evict()
        current_user_mcp_tool.set(tool)
        return tool

    def _evict(self) -> None:
        while len(self._tools) > self.max_users:
            oid, tool = self._tools.popitem(last=False)
            self._locks.pop(oid, None)
            self._close_later(tool, self.close_after_seconds)  # an in-flight run may still be using it

    def _close_later(self, tool: UserMCPTool, delay: float) -> None:
        async def close() -> None:
            await asyncio.sleep(delay)
            await _close(tool)

        task = asyncio.get_running_loop().create_task(close())
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    async def close(self) -> None:
        for task in list(self._closing):
            task.cancel()
        tools, self._tools = list(self._tools.values()), OrderedDict()
        self._locks.clear()
        await asyncio.gather(*(_close(t) for t in tools))


async def _close(tool: UserMCPTool) -> None:
    try:
        async with asyncio.timeout(10):
            await tool.close()
    except Exception:  # noqa: BLE001 - closing a session that is already gone
        log.debug("closing a user's MCP session failed", exc_info=True)
