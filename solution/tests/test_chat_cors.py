"""ASI03 fail-closed contract for CORS: preflight never reaches auth or the agent, and CORS grants nothing."""

import pytest
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from test_chat_auth import SpyAgent, SpyStore, agui_body

from chat_api.app import create_app
from chat_api.auth import RequireUser

UI_ORIGIN = "https://chat-ui.example.australiaeast.azurecontainerapps.io"
OTHER_ORIGIN = "https://evil.example"


class CountingRequireUser(RequireUser):
    def __init__(self, validator) -> None:
        super().__init__(validator)
        self.calls = 0

    async def __call__(self, request: Request):
        self.calls += 1
        return await super().__call__(request)


@pytest.fixture
def cors_harness(monkeypatch, chat_validator):
    def build(origins: str | None):
        if origins is None:
            monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
        else:
            monkeypatch.setenv("CORS_ALLOWED_ORIGINS", origins)
        agent, store, require_user = SpyAgent(), SpyStore(), CountingRequireUser(chat_validator)
        return agent, require_user, TestClient(create_app(agent, store, require_user))

    return build


def preflight(client: TestClient, origin: str):
    return client.options(
        "/",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )


def test_allowed_origin_preflight_is_answered_without_auth_or_agent(cors_harness):
    agent, require_user, client = cors_harness(UI_ORIGIN)
    response = preflight(client, UI_ORIGIN)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == UI_ORIGIN
    assert [m.strip() for m in response.headers["access-control-allow-methods"].split(",")] == ["POST"]
    allowed_headers = {h.strip().lower() for h in response.headers["access-control-allow-headers"].split(",")}
    assert {"authorization", "content-type"} <= allowed_headers
    assert response.headers["access-control-max-age"] == "600"
    assert "access-control-allow-credentials" not in response.headers
    assert require_user.calls == 0
    assert agent.runs == []


def test_disallowed_origin_preflight_gets_no_allow_origin(cors_harness):
    agent, require_user, client = cors_harness(UI_ORIGIN)
    response = preflight(client, OTHER_ORIGIN)
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    assert require_user.calls == 0
    assert agent.runs == []


def test_unauthenticated_post_from_allowed_origin_is_401_with_allow_origin(cors_harness):
    agent, _, client = cors_harness(UI_ORIGIN)
    response = client.post("/", json=agui_body("t1"), headers={"Origin": UI_ORIGIN})
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == UI_ORIGIN
    assert agent.runs == []


def test_authenticated_post_from_allowed_origin_streams_with_allow_origin(cors_harness, sim):
    agent, _, client = cors_harness(UI_ORIGIN)
    headers = {"Origin": UI_ORIGIN, "Authorization": f"Bearer {sim.user_token('alice')}"}
    with client.stream("POST", "/", json=agui_body("t1"), headers=headers) as response:
        response.read()
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["access-control-allow-origin"] == UI_ORIGIN
    assert "access-control-allow-credentials" not in response.headers
    assert len(agent.runs) == 1


def test_unset_origins_adds_no_cors(cors_harness):
    agent, require_user, client = cors_harness(None)
    response = preflight(client, UI_ORIGIN)
    assert not [h for h in response.headers if h.lower().startswith("access-control-allow-")]
    assert require_user.calls == 0
    assert agent.runs == []


@pytest.mark.parametrize(
    "origins",
    ["*", f"{UI_ORIGIN},*", "https://*.example", "https://x.example/app", "https://x.example/", "chat-ui.example"],
    ids=["wildcard", "wildcard-in-list", "wildcard-host", "path", "trailing-slash", "no-scheme"],
)
def test_malformed_origins_fail_at_app_creation(cors_harness, origins):
    with pytest.raises(ValueError, match="CORS_ALLOWED_ORIGINS"):
        cors_harness(origins)


@pytest.mark.parametrize("origins", ["", "   ", " , "], ids=["empty", "whitespace", "commas"])
def test_empty_origins_add_no_middleware(cors_harness, origins):
    _, _, client = cors_harness(origins)
    assert not [m for m in client.app.user_middleware if m.cls is CORSMiddleware]


def test_cli_client_id_still_accepted(cors_harness, sim):
    # The CLI sends no Origin; CORS must not change its path.
    agent, _, client = cors_harness(UI_ORIGIN)
    response = client.post("/", json=agui_body("t1"), headers={"Authorization": f"Bearer {sim.user_token('bob')}"})
    response.read()
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    assert len(agent.runs) == 1
