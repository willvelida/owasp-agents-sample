"""ASI03 at the MCP server: 401 without a valid OBO token, and the user always comes from the token oid."""

import json
from typing import Any

import pytest
from conftest import ENV
from fastapi.testclient import TestClient

from health_mcp.auth import HealthTokenVerifier
from health_mcp.server import build_server

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


class SpyRepository:
    def __init__(self) -> None:
        self.queries: list[tuple[str, str]] = []

    async def by_date(self, user_id, document_type, date):
        self.queries.append((user_id, document_type))
        return [{"userId": user_id, "documentType": document_type, "date": date}]

    async def by_date_range(self, user_id, document_type, start, end, page, page_size):
        self.queries.append((user_id, document_type))
        return [{"userId": user_id, "documentType": document_type}]

    async def records(self, user_id, document_type, page, page_size):
        self.queries.append((user_id, document_type))
        return [{"userId": user_id, "documentType": document_type}]

    async def delete(self, user_id, document_type):
        self.queries.append((user_id, f"delete:{document_type}"))
        return 0


@pytest.fixture
def mcp(mcp_validator, sim):
    repo = SpyRepository()
    server = build_server(repo, HealthTokenVerifier(mcp_validator), issuer_url=sim.issuer)
    with TestClient(server.streamable_http_app()) as client:
        yield repo, client


def call(client: TestClient, tool: str, arguments: dict[str, Any], token: str | None) -> Any:
    headers = dict(MCP_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
    return client.post("/mcp", json=body, headers=headers)


def result_of(response) -> dict[str, Any]:
    for line in response.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:])["result"]
    return response.json()["result"]


def test_no_token_is_401_with_zero_queries(mcp):
    repo, client = mcp
    assert call(client, "get_sleep_records", {}, None).status_code == 401
    assert repo.queries == []


async def test_user_token_without_obo_is_401(mcp, sim):
    repo, client = mcp
    assert call(client, "get_sleep_records", {}, sim.user_token("alice")).status_code == 401
    assert repo.queries == []


async def test_alice_token_never_reads_bob(mcp, sim):
    repo, client = mcp
    token = await sim.obo(sim.user_token("alice"), ENV["CHAT_AGENT_APP_ID"])
    for tool, args in [
        ("get_sleep_records", {"user_id": "bob"}),
        ("get_sleep_by_date", {"date": "2026-10-14", "user_id": ENV["BOB_OID"]}),
        ("get_food_by_date_range", {"start_date": "2026-10-01", "end_date": "2026-10-14", "userId": "bob"}),
        ("delete_records", {"document_type": "sleep", "user_id": ENV["BOB_OID"]}),
    ]:
        response = call(client, tool, args, token)
        assert response.status_code == 200, response.text
        assert ENV["BOB_OID"] not in json.dumps(result_of(response))
    assert repo.queries
    assert {user for user, _ in repo.queries} == {ENV["ALICE_OID"]}


async def test_tools_do_not_expose_user_id(mcp, sim):
    _, client = mcp
    token = await sim.obo(sim.user_token("alice"), ENV["CHAT_AGENT_APP_ID"])
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    response = client.post("/mcp", json=body, headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"})
    tools = result_of(response)["tools"]
    assert len(tools) == 13
    for tool in tools:
        assert "user_id" not in tool["inputSchema"].get("properties", {})
