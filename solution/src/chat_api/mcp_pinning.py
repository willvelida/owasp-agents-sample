"""Client-side MCP descriptor pinning (ASI04 runtime).

Every tools/list response the chat agent receives is compared with policies/mcp_tools.lock.json
before MAF turns it into tools the model can see. An added, removed, or reworded tool raises
DescriptorPinError, which fails the run before the model call. The health MCP server makes the same
check at startup, so a tampered server normally never becomes ready in the first place.
"""

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from agent_framework import MCPStreamableHTTPTool

from governance import descriptors

log = logging.getLogger("chat_api.mcp_pinning")


class DescriptorPinError(RuntimeError):
    pass


def pinned_listing(
    list_tools: Callable[..., Awaitable[Any]], pinned: Mapping[str, str]
) -> Callable[..., Awaitable[Any]]:
    async def checked(*args: Any, **kwargs: Any) -> Any:
        result = await list_tools(*args, **kwargs)
        problems = descriptors.mismatches(descriptors.digests(result.tools), pinned)
        if getattr(result, "nextCursor", None):
            problems.append("paginated tools/list is not pinned")
        if problems:
            log.critical("MCP descriptor pin mismatch: %s", "; ".join(problems))
            raise DescriptorPinError("MCP tool descriptors do not match the lock: " + "; ".join(problems))
        return result

    checked.pinned = True  # type: ignore[attr-defined]
    return checked


class PinnedMCPStreamableHTTPTool(MCPStreamableHTTPTool):
    def __init__(self, *args: Any, pinned: Mapping[str, str], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pinned = dict(pinned)

    async def _load_tools_locked(self) -> None:
        await self._ensure_connected()
        session = self.session
        if session is not None and not getattr(session.list_tools, "pinned", False):
            session.list_tools = pinned_listing(session.list_tools, self._pinned)  # type: ignore[method-assign]
        await super()._load_tools_locked()
