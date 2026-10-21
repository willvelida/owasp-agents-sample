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
from chat_api.middleware.memory_guard import (
    MAX_STORED_MESSAGES,
    TTL_SECONDS,
    MemoryGate,
    cap_fields,
    digest,
    keep_last,
)

log = logging.getLogger("chat_api.history")

# ASI06: partitioned by /userId with a 90 day default TTL (seed locally, Bicep on Azure). Every read and write
# names the caller's oid as the partition key, so another user's conversation is simply not there.
CONTAINER = "chat_history"


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
        ).get_container_client(CONTAINER)

    async def get(self, session_id: str, oid: str) -> dict[str, Any] | None:
        try:
            return await self.container.read_item(session_id, partition_key=oid)
        except CosmosResourceNotFoundError:
            return None

    async def get_owned(self, session_id: str, oid: str) -> dict[str, Any] | None:
        # ASI03: another user's session is indistinguishable from a missing one.
        doc = await self.get(session_id, oid)
        return doc if doc and doc.get("userId") == oid else None

    async def list_for(self, oid: str) -> list[dict[str, Any]]:
        query = "SELECT c.id, c.title, c.updatedAt FROM c WHERE c.userId = @u ORDER BY c.updatedAt DESC"
        items = self.container.query_items(query, parameters=[{"name": "@u", "value": oid}], partition_key=oid)
        return [item async for item in items]

    async def delete_owned(self, session_id: str, oid: str) -> bool:
        if await self.get_owned(session_id, oid) is None:
            return False
        await self.container.delete_item(session_id, partition_key=oid)
        return True

    async def upsert(self, doc: dict[str, Any]) -> None:
        await self.container.upsert_item(doc)

    async def close(self) -> None:
        await self._client.close()


class CosmosHistoryProvider(HistoryProvider):
    """Persists conversations, bound to the caller's oid.

    ASI06: hydrates at most the last 50 messages, stores at most 100 per conversation with every text field capped
    at 10,000 characters, and drops any turn that AGT MemoryGuard flags before it is written (memory_guard.py).
    """

    def __init__(self, store: CosmosConversationStore, gate: MemoryGate | None = None) -> None:
        super().__init__("cosmos_history")
        self._store = store
        self._gate = gate or MemoryGate()

    async def get_messages(self, session_id: str | None, *, state: dict[str, Any] | None = None, **_: Any):
        if not session_id:
            return []
        oid = require_principal().oid
        doc = await self._store.get(session_id, oid)
        if doc is None:
            return []
        if doc.get("userId") != oid:
            # ASI03: fail closed rather than load another user's memory.
            raise PermissionError("session belongs to another user")
        window = self._gate.hydrate(doc.get("messages", []), doc.get("integrity", []))
        return [Message.from_dict(m) for m in window]

    async def save_messages(
        self, session_id: str | None, messages: Sequence[Message], *, state: dict[str, Any] | None = None, **_: Any
    ) -> None:
        if not session_id or not messages:
            return
        oid = require_principal().oid
        turn = [cap_fields(m.to_dict()) for m in messages]
        if self._gate.screen_turn(turn):
            log.warning("memory guard dropped a turn of %d messages from conversation %s", len(turn), session_id)
            return
        now = datetime.now(UTC).isoformat()
        doc = await self._store.get(session_id, oid) or {
            "id": session_id,
            "sessionId": session_id,
            "userId": oid,
            "title": _title(messages),
            "createdAt": now,
            "messages": [],
            "integrity": [],
        }
        if doc.get("userId") != oid:
            raise PermissionError("session belongs to another user")
        stored = list(doc.get("messages", []))
        hashes = list(doc.get("integrity", []))
        # Messages stored before this turn keep their recorded hashes; a mismatch is caught on read.
        hashes = (hashes + [""] * len(stored))[: len(stored)]
        pairs = [*zip(stored, hashes, strict=True), *((m, digest(m)) for m in turn)]
        pairs = keep_last(pairs, MAX_STORED_MESSAGES, role_of=lambda p: p[0].get("role"))
        doc["messages"] = [m for m, _ in pairs]
        doc["integrity"] = [h for _, h in pairs]
        doc["updatedAt"] = now
        doc["ttl"] = TTL_SECONDS
        await self._store.upsert(doc)
        log.info("saved %d messages to conversation %s", len(messages), session_id)


def _title(messages: Sequence[Message]) -> str:
    for message in messages:
        if message.role == "user" and message.text:
            return message.text[:80]
    return "New conversation"
