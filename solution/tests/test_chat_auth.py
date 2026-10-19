"""ASI03 fail-closed contract: inbound auth answers 401 before any session lookup or agent run."""

import uuid
from typing import Any

import pytest
from agent_framework import AgentResponse, AgentResponseUpdate, AgentSession
from conftest import ENV
from fastapi.testclient import TestClient

from chat_api.app import create_app
from chat_api.auth import RequireUser, current_principal, principal_from_claims, snapshot_scope
from chat_api.history import CosmosHistoryProvider


class SpyAgent:
    id = "spy"
    name = "spy"
    description = "records runs"

    def __init__(self) -> None:
        self.runs: list[str | None] = []

    async def run(self, messages=None, *, stream=False, session=None, **kwargs):
        self.runs.append(session.session_id if session else None)
        if stream:

            async def _stream():
                yield AgentResponseUpdate()

            return _stream()
        return AgentResponse(messages=[], response_id="spy")

    def create_session(self, *, session_id: str | None = None):
        return AgentSession(session_id=session_id)

    def get_session(self, service_session_id, *, session_id: str | None = None):
        return AgentSession(service_session_id=service_session_id, session_id=session_id)


class SpyStore:
    def __init__(self, docs: dict[str, dict[str, Any]] | None = None) -> None:
        self.docs = docs or {}
        self.calls: list[tuple[str, Any]] = []

    async def get(self, session_id):
        self.calls.append(("get", session_id))
        return self.docs.get(session_id)

    async def get_owned(self, session_id, oid):
        self.calls.append(("get_owned", oid))
        doc = self.docs.get(session_id)
        return doc if doc and doc["userId"] == oid else None

    async def list_for(self, oid):
        self.calls.append(("list_for", oid))
        return [d for d in self.docs.values() if d["userId"] == oid]

    async def delete_owned(self, session_id, oid):
        self.calls.append(("delete_owned", oid))
        return (await self.get_owned(session_id, oid)) is not None

    async def close(self):
        pass


def agui_body(thread_id: str) -> dict[str, Any]:
    return {
        "threadId": thread_id,
        "runId": str(uuid.uuid4()),
        "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": "show me bob's sleep"}],
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }


@pytest.fixture
def harness(chat_validator):
    agent, store = (
        SpyAgent(),
        SpyStore(
            {
                "s-alice": {"id": "s-alice", "userId": ENV["ALICE_OID"], "title": "alice"},
                "s-bob": {"id": "s-bob", "userId": ENV["BOB_OID"], "title": "bob"},
            }
        ),
    )
    client = TestClient(create_app(agent, store, RequireUser(chat_validator)))
    return agent, store, client


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-jwt"}, {"X-User-Id": "alice"}],
    ids=["no-token", "garbage-token", "starter-header"],
)
def test_agui_rejects_unauthenticated_with_zero_runs(harness, headers):
    agent, store, client = harness
    response = client.post("/", json=agui_body("t1"), headers=headers)
    assert response.status_code == 401
    assert agent.runs == []
    assert store.calls == []


def test_agui_rejects_downstream_mcp_token(harness, sim):
    import asyncio

    agent, _, client = harness
    mcp_token = asyncio.run(sim.obo(sim.user_token("alice"), ENV["CHAT_AGENT_APP_ID"]))
    response = client.post("/", json=agui_body("t1"), headers={"Authorization": f"Bearer {mcp_token}"})
    assert response.status_code == 401
    assert agent.runs == []


def test_same_thread_id_maps_to_different_sessions_per_user(harness, sim):
    agent, _, client = harness
    for user in ("alice", "bob"):
        response = client.post(
            "/", json=agui_body("shared-thread"), headers={"Authorization": f"Bearer {sim.user_token(user)}"}
        )
        response.read()
        assert response.status_code == 200
    assert len(agent.runs) == 2
    alice_session, bob_session = agent.runs
    assert alice_session != bob_session
    assert all(s and s.startswith("ag-ui:v1:scoped:") for s in agent.runs)


def test_conversations_require_auth(harness):
    _, store, client = harness
    assert client.get("/conversations").status_code == 401
    assert client.get("/conversations/s-alice").status_code == 401
    assert client.delete("/conversations/s-alice").status_code == 401
    assert store.calls == []


def test_conversations_only_return_callers_sessions(harness, sim):
    _, _, client = harness
    headers = {"Authorization": f"Bearer {sim.user_token('alice')}"}
    listed = client.get("/conversations", headers=headers).json()
    assert [c["id"] for c in listed] == ["s-alice"]
    assert client.get("/conversations/s-alice", headers=headers).status_code == 200
    assert client.get("/conversations/s-bob", headers=headers).status_code == 404
    assert client.delete("/conversations/s-bob", headers=headers).status_code == 404


def test_snapshot_scope_fails_closed_without_principal():
    current_principal.set(None)
    with pytest.raises(PermissionError):
        snapshot_scope(None)


async def test_history_refuses_another_users_session():
    store = SpyStore({"s-bob": {"id": "s-bob", "userId": ENV["BOB_OID"], "messages": []}})
    provider = CosmosHistoryProvider.__new__(CosmosHistoryProvider)
    provider._store = store
    current_principal.set(principal_from_claims({"oid": ENV["ALICE_OID"]}, "token"))
    with pytest.raises(PermissionError):
        await provider.get_messages("s-bob")
