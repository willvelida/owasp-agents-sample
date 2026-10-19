"""Per-conversation tool-call budget (ASI02).

The budget is keyed by the signed-in user's oid plus the session id, so one user can never spend or
reset another user's budget, and a reservation for a whole tool batch is atomic: concurrent requests
on the same conversation cannot overspend it. The store is in-process; the Azure app runs one replica.
"""

import asyncio
from collections import OrderedDict


class ToolBudget:
    def __init__(self, limit: int, *, max_sessions: int = 10_000) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self.limit = limit
        self._used: OrderedDict[tuple[str, str], int] = OrderedDict()
        self._lock = asyncio.Lock()
        self._max_sessions = max_sessions

    async def reserve(self, oid: str, session_id: str, calls: int) -> bool:
        """Reserve `calls` tool calls for the conversation; False (and nothing reserved) if over budget."""
        key = (oid, session_id)
        async with self._lock:
            used = self._used.get(key, 0)
            if used + calls > self.limit:
                return False
            self._used[key] = used + calls
            self._used.move_to_end(key)
            while len(self._used) > self._max_sessions:
                self._used.popitem(last=False)
            return True

    async def used(self, oid: str, session_id: str) -> int:
        async with self._lock:
            return self._used.get((oid, session_id), 0)
