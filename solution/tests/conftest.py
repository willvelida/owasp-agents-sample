import os
from typing import Any

import jwt
import pytest

from auth_common import IssuerConfig, JwtValidator
from local_issuer.app import Simulator

ENV = {
    "TENANT_ID": "11111111-1111-1111-1111-111111111111",
    "BLUEPRINT_APP_ID": "22222222-2222-2222-2222-222222222222",
    "CHAT_AGENT_APP_ID": "33333333-3333-3333-3333-333333333333",
    "HEALTH_MCP_APP_ID": "44444444-4444-4444-4444-444444444444",
    "CLI_APP_ID": "55555555-5555-5555-5555-555555555555",
    "REPORT_API_APP_ID": "66666666-6666-6666-6666-666666666666",
    "ALICE_OID": "aaaaaaaa-0000-0000-0000-00000000a11c",
    "BOB_OID": "bbbbbbbb-0000-0000-0000-000000000b0b",
    "LOCAL_ISSUER_URL": "http://local-issuer:8100",
    "IDENTITY_MODE": "local",
    "MCP_ALLOWED_HOSTS": "testserver",
}


class StaticJwks:
    def __init__(self, sim: Simulator) -> None:
        self.sim = sim

    def get_signing_key_from_jwt(self, token: str) -> Any:
        return jwt.PyJWK(self.sim.jwks()["keys"][0])


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    for name in ("CONTAINER_APP_NAME", "CONTAINER_APP_ENV_DNS_SUFFIX", "IDENTITY_ENDPOINT", "MSI_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    return dict(os.environ)


@pytest.fixture
def sim(env: dict[str, str]) -> Simulator:
    return Simulator(env)


def local_validator(sim: Simulator, *, audience: str, scope: str, clients: set[str] | None) -> JwtValidator:
    issuer = IssuerConfig(mode="local", issuer=sim.issuer, jwks_uri=f"{sim.issuer}/jwks")
    return JwtValidator(
        issuer, audience=audience, required_scope=scope, allowed_client_ids=clients, jwks_client=StaticJwks(sim)
    )


@pytest.fixture
def chat_validator(sim: Simulator) -> JwtValidator:
    return local_validator(sim, audience=ENV["BLUEPRINT_APP_ID"], scope="access_as_user", clients={ENV["CLI_APP_ID"]})


@pytest.fixture
def mcp_validator(sim: Simulator) -> JwtValidator:
    return local_validator(
        sim, audience=ENV["HEALTH_MCP_APP_ID"], scope="Health.Read", clients={ENV["CHAT_AGENT_APP_ID"]}
    )
