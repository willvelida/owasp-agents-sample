"""Conversation history in Cosmos DB, bound to the signed-in user."""

import logging
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from agent_framework import HistoryProvider, Message
from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from auth_common.azure_credential import cosmos_credential
from chat_api.auth import require_principal

log = logging.getLogger("chat_api.history")


class CosmosConversationStore:
    def __init__(self) -> None:
        endpoint = os.environ.get("COSMOS_ENDPOINT", "http://localhost:8081")
        self._client = CosmosClient(
            endpoint,
            # ASI03: Entra identity outside the local emulator; no account key.
            credential=cosmos_credential(endpoint),
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

    async def get_owned(self, session_id: str, oid: str) -> dict[str, Any] | None:
        # ASI03: another user's session is indistinguishable from a missing one.
        doc = await self.get(session_id)
        return doc if doc and doc.get("userId") == oid else None

    async def list_for(self, oid: str) -> list[dict[str, Any]]:
        query = "SELECT c.id, c.title, c.updatedAt FROM c WHERE c.userId = @u ORDER BY c.updatedAt DESC"
        items = self.container.query_items(query, parameters=[{"name": "@u", "value": oid}])
        return [item async for item in items]

    async def delete_owned(self, session_id: str, oid: str) -> bool:
        if await self.get_owned(session_id, oid) is None:
            return False
        await self.container.delete_item(session_id, partition_key=session_id)
        return True

    async def close(self) -> None:
        await self._client.close()


class CosmosHistoryProvider(HistoryProvider):
    """Persists full conversations, bound to the caller's oid.

    ASI06 (starter): no cap on messages loaded or stored, no per-message size limit, no TTL,
    and nothing screens what gets written back into memory.
    """

    def __init__(self, store: CosmosConversationStore) -> None:
        super().__init__("cosmos_history")
        self._store = store

    async def get_messages(self, session_id: str | None, *, state: dict[str, Any] | None = None, **_: Any):
        if not session_id:
            return []
        oid = require_principal().oid
        doc = await self._store.get(session_id)
        if doc is None:
            return []
        if doc.get("userId") != oid:
            # ASI03: fail closed rather than load another user's memory.
            raise PermissionError("session belongs to another user")
        return [Message.from_dict(m) for m in doc["messages"]]

    async def save_messages(
        self, session_id: str | None, messages: Sequence[Message], *, state: dict[str, Any] | None = None, **_: Any
    ) -> None:
        if not session_id or not messages:
            return
        oid = require_principal().oid
        now = datetime.now(UTC).isoformat()
        doc = await self._store.get(session_id) or {
            "id": session_id,
            "sessionId": session_id,
            "userId": oid,
            "title": _title(messages),
            "createdAt": now,
            "messages": [],
        }
        if doc.get("userId") != oid:
            raise PermissionError("session belongs to another user")
        doc["messages"].extend(m.to_dict() for m in messages)
        doc["updatedAt"] = now
        await self._store.container.upsert_item(doc)
        log.info("saved %d messages to conversation %s", len(messages), session_id)


def _title(messages: Sequence[Message]) -> str:
    for message in messages:
        if message.role == "user" and message.text:
            return message.text[:80]
    return "New conversation"
