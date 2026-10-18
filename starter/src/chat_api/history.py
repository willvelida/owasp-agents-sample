"""Conversation history in Cosmos DB, plus the request-scoped user."""

import contextvars
import logging
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from agent_framework import HistoryProvider, Message
from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError

DEFAULT_USER_ID = os.environ.get("DEFAULT_USER_ID", "alice")
current_user: contextvars.ContextVar[str] = contextvars.ContextVar("current_user", default=DEFAULT_USER_ID)
log = logging.getLogger("chat_api.history")


class CosmosConversationStore:
    def __init__(self) -> None:
        self._client = CosmosClient(
            os.environ.get("COSMOS_ENDPOINT", "http://localhost:8081"),
            # ASI03 (starter): account key with full access to every user's conversations.
            credential=os.environ["COSMOS_KEY"],
            enable_endpoint_discovery=False,
        )
        self.container: ContainerProxy = self._client.get_database_client(
            os.environ.get("COSMOS_DATABASE", "biotrackr")
        ).get_container_client("conversations")

    async def get(self, session_id: str) -> dict[str, Any] | None:
        try:
            return await self.container.read_item(session_id, partition_key=session_id)
        except CosmosResourceNotFoundError:
            return None

    async def list_all(self) -> list[dict[str, Any]]:
        # ASI03 (starter): lists every user's sessions, whoever asks.
        query = "SELECT c.id, c.userId, c.title, c.updatedAt FROM c ORDER BY c.updatedAt DESC"
        return [item async for item in self.container.query_items(query)]

    async def delete(self, session_id: str) -> bool:
        try:
            await self.container.delete_item(session_id, partition_key=session_id)
            return True
        except CosmosResourceNotFoundError:
            return False

    async def close(self) -> None:
        await self._client.close()


class CosmosHistoryProvider(HistoryProvider):
    """Persists full conversations.

    ASI06 (starter): no cap on messages loaded or stored, no per-message size limit, no TTL,
    and nothing screens what gets written back into memory.
    """

    def __init__(self, store: CosmosConversationStore) -> None:
        super().__init__("cosmos_history")
        self._store = store

    async def get_messages(self, session_id: str | None, *, state: dict[str, Any] | None = None, **_: Any):
        if not session_id:
            return []
        doc = await self._store.get(session_id)
        return [Message.from_dict(m) for m in doc["messages"]] if doc else []

    async def save_messages(
        self, session_id: str | None, messages: Sequence[Message], *, state: dict[str, Any] | None = None, **_: Any
    ) -> None:
        if not session_id or not messages:
            return
        now = datetime.now(UTC).isoformat()
        doc = await self._store.get(session_id) or {
            "id": session_id,
            "sessionId": session_id,
            "userId": current_user.get(),
            "title": _title(messages),
            "createdAt": now,
            "messages": [],
        }
        doc["messages"].extend(m.to_dict() for m in messages)
        doc["updatedAt"] = now
        await self._store.container.upsert_item(doc)
        log.info("saved %d messages to conversation %s", len(messages), session_id)


def _title(messages: Sequence[Message]) -> str:
    for message in messages:
        if message.role == "user" and message.text:
            return message.text[:80]
    return "New conversation"
