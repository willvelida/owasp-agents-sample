"""Per-conversation tool-call budget (ASI02) and token budget (ASI08).

The budget is keyed by the signed-in user's oid plus the session id, so one user can never spend or
reset another user's budget, and a reservation for a whole tool batch is atomic: concurrent requests
on the same conversation cannot overspend it. The store is in-process; the Azure app runs one replica.
"""

import asyncio
from collections import Counter, OrderedDict
from collections.abc import Mapping

_TOTAL = "*"


class ToolBudget:
    def __init__(self, limit: int, *, tool_limits: Mapping[str, int] | None = None, max_sessions: int = 10_000) -> None:
        if limit < 1 or any(v < 1 for v in (tool_limits or {}).values()):
            raise ValueError("limits must be at least 1")
        self.limit = limit
        # Per-conversation caps for single tools (for example generate_report: 2). MAF's max_invocations counts
        # across the tool instance's lifetime, which on a shared agent is every user, so it is not used.
        self.tool_limits = dict(tool_limits or {})
        self._used: OrderedDict[tuple[str, str], Counter[str]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._max_sessions = max_sessions

    async def reserve(self, oid: str, session_id: str, calls: int, tools: Mapping[str, int] | None = None) -> bool:
        """Reserve a whole batch for the conversation; False (and nothing reserved) if any limit would be exceeded.

        `calls` is the batch size; `tools` optionally counts the batch per tool name for the per-tool limits.
        """
        key = (oid, session_id)
        async with self._lock:
            used = self._used.get(key, Counter())
            if used[_TOTAL] + calls > self.limit:
                return False
            for name, count in (tools or {}).items():
                if name in self.tool_limits and used[name] + count > self.tool_limits[name]:
                    return False
            updated = Counter(used)
            updated[_TOTAL] += calls
            updated.update({n: c for n, c in (tools or {}).items() if n in self.tool_limits})
            self._used[key] = updated
            self._used.move_to_end(key)
            while len(self._used) > self._max_sessions:
                self._used.popitem(last=False)
            return True

    async def used(self, oid: str, session_id: str, tool: str | None = None) -> int:
        async with self._lock:
            return self._used.get((oid, session_id), Counter())[tool or _TOTAL]


class TokenBudget:
    """Model tokens per conversation (ASI08), keyed like the tool budget and also in-process.

    Accounting happens after each model call, so a run can overshoot by at most one call; the next model call in
    the run and every later run of the conversation are refused.
    """

    def __init__(self, limit: int, *, max_sessions: int = 10_000) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self.limit = limit
        self._used: OrderedDict[tuple[str, str], int] = OrderedDict()
        self._max_sessions = max_sessions

    def add(self, oid: str, session_id: str, tokens: int) -> int:
        key = (oid, session_id)
        self._used[key] = self._used.get(key, 0) + max(0, tokens)
        self._used.move_to_end(key)
        while len(self._used) > self._max_sessions:
            self._used.popitem(last=False)
        return self._used[key]

    def used(self, oid: str, session_id: str) -> int:
        return self._used.get((oid, session_id), 0)

    def exhausted(self, oid: str, session_id: str) -> bool:
        return self.used(oid, session_id) >= self.limit
