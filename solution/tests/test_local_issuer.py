"""ADR-0018: the stage-only simulator mimics the OBO claim shape and refuses Azure."""

import jwt
import pytest
from conftest import ENV
from fastapi.testclient import TestClient

from local_issuer.app import AZURE_MARKERS, create_app, refuse_azure


@pytest.mark.parametrize("marker", AZURE_MARKERS)
def test_refuses_every_azure_marker(monkeypatch, marker):
    monkeypatch.setenv(marker, "set")
    with pytest.raises(SystemExit):
        refuse_azure()


def test_starts_without_azure_markers():
    refuse_azure()


async def test_obo_claim_shape_matches_entra_contract(sim):
    user_token = sim.user_token("alice")
    user = jwt.decode(user_token, options={"verify_signature": False})
    assert user["aud"] == ENV["BLUEPRINT_APP_ID"]
    assert user["scp"] == "access_as_user"
    assert user["oid"] == ENV["ALICE_OID"]

    mcp = jwt.decode(await sim.obo(user_token, ENV["CHAT_AGENT_APP_ID"]), options={"verify_signature": False})
    assert mcp["aud"] == ENV["HEALTH_MCP_APP_ID"]
    assert mcp["scp"] == "Health.Read"
    assert mcp["oid"] == ENV["ALICE_OID"]
    assert mcp["azp"] == ENV["CHAT_AGENT_APP_ID"]


async def test_obo_refuses_unknown_agent_identity(sim):
    with pytest.raises(PermissionError):
        await sim.obo(sim.user_token("alice"), "not-the-chat-agent")


def test_http_obo_requires_bearer(sim):
    client = TestClient(create_app(sim))
    response = client.get("/AuthorizationHeader/HealthMcp", params={"AgentIdentity": ENV["CHAT_AGENT_APP_ID"]})
    assert response.status_code == 401


def test_http_obo_rejects_mcp_token_as_input(sim):
    client = TestClient(create_app(sim))
    user = client.get("/token", params={"user": "bob"}).json()["access_token"]
    ok = client.get(
        "/AuthorizationHeader/HealthMcp",
        params={"AgentIdentity": ENV["CHAT_AGENT_APP_ID"]},
        headers={"Authorization": f"Bearer {user}"},
    )
    assert ok.status_code == 200
    mcp_token = ok.json()["authorizationHeader"].removeprefix("Bearer ")
    replay = client.get(
        "/AuthorizationHeader/HealthMcp",
        params={"AgentIdentity": ENV["CHAT_AGENT_APP_ID"]},
        headers={"Authorization": f"Bearer {mcp_token}"},
    )
    assert replay.status_code == 401


def test_unknown_user_is_404(sim):
    assert TestClient(create_app(sim)).get("/token", params={"user": "mallory"}).status_code == 404
