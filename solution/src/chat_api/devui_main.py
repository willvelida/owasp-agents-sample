"""Run the chat agent in DevUI for local visuals.

DevUI runs the agent in-process and cannot carry a per-user JWT, so the solution allows it only with
IDENTITY_MODE=local: each run signs in DEVUI_USER (default alice) at the stage-only simulator and goes
through the same OBO path as the AG-UI endpoint. Run from solution/ with the offline stack up:

    $env:IDENTITY_MODE = "local"; uv run --env-file .env python -m chat_api.devui_main
"""

import logging
import os

import httpx
from agent_framework_devui import serve

from auth_common import IssuerConfig, identity_mode, issuer_for_mode
from chat_api.agent import build_agent
from chat_api.auth import Principal, build_validator, principal_from_claims
from chat_api.history import CosmosConversationStore, CosmosHistoryProvider
from chat_api.identity import DownstreamTokenProvider

ISSUER = "http://127.0.0.1:8100"


def main() -> None:
    if identity_mode() != "local":
        raise SystemExit("DevUI is available only with IDENTITY_MODE=local (it has no per-user sign-in)")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    os.environ.setdefault("COSMOS_ENDPOINT", "http://localhost:8081")
    os.environ.setdefault("MCP_URL", "http://localhost:8001/mcp")
    issuer_url = os.environ.get("DEVUI_ISSUER_URL", ISSUER)
    user = os.environ.get("DEVUI_USER", "alice")
    # Tokens carry the simulator's in-network issuer; fetch its keys through the published port.
    issuer = issuer_for_mode("local")
    validator = build_validator(IssuerConfig(mode="local", issuer=issuer.issuer, jwks_uri=f"{issuer_url}/jwks"))

    async def sign_in() -> Principal:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{issuer_url}/token", params={"user": user})
            response.raise_for_status()
        token = response.json()["access_token"]
        return principal_from_claims(await validator.validate(token), token)

    agent = build_agent(
        CosmosHistoryProvider(CosmosConversationStore()),
        DownstreamTokenProvider(base_url=issuer_url),
        principal_fallback=sign_in,
    )
    serve(
        entities=[agent],
        host="127.0.0.1",
        port=int(os.environ.get("DEVUI_PORT", "8090")),
        auto_open=os.environ.get("DEVUI_OPEN", "1") == "1",
    )


if __name__ == "__main__":
    main()
