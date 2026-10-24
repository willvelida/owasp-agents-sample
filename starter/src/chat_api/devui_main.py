"""Run the chat agent in DevUI on the host or the starter's container network.

DevUI runs the agent in-process with no per-user identity; it acts as DEFAULT_USER_ID (alice).
From starter/, use the Compose profile to export traces to Aspire:

    podman compose --profile devui up -d devui

Or run on the host with the stack up (no Aspire export by default):

    uv run --env-file .env python -m chat_api.devui_main
"""

import logging
import os
import secrets

from agent_framework_devui import serve

from chat_api.agent import build_agent
from chat_api.history import CosmosConversationStore, CosmosHistoryProvider
from telemetry import setup_telemetry

log = logging.getLogger(__name__)


def main() -> None:
    """Configure telemetry and start DevUI with an explicit bearer token."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    os.environ.setdefault("COSMOS_ENDPOINT", "http://localhost:8081")
    os.environ.setdefault("MCP_URL", "http://localhost:8001/mcp")
    setup_telemetry("biotrackr-devui")
    auth_token = os.environ.get("DEVUI_AUTH_TOKEN")
    if not auth_token:
        auth_token = secrets.token_urlsafe(32)
        log.info("DevUI bearer token: %s", auth_token)
    agent = build_agent(CosmosHistoryProvider(CosmosConversationStore()))
    serve(
        entities=[agent],
        host=os.environ.get("DEVUI_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEVUI_PORT", "8090")),
        auto_open=os.environ.get("DEVUI_OPEN", "1") == "1",
        auth_token=auth_token,
    )


if __name__ == "__main__":
    main()
