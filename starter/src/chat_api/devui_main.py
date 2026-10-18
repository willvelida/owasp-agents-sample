"""Run the chat agent in DevUI for local visuals.

DevUI runs the agent in-process with no per-user identity; it acts as DEFAULT_USER_ID (alice).
Run from starter/ with the stack up:

    uv run --env-file .env python -m chat_api.devui_main
"""

import logging
import os

from agent_framework_devui import serve

from chat_api.agent import build_agent
from chat_api.history import CosmosConversationStore, CosmosHistoryProvider


def main() -> None:
    # DevUI logs its auto-generated bearer token at INFO; set DEVUI_AUTH_TOKEN to choose your own.
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    os.environ.setdefault("COSMOS_ENDPOINT", "http://localhost:8081")
    os.environ.setdefault("MCP_URL", "http://localhost:8001/mcp")
    agent = build_agent(CosmosHistoryProvider(CosmosConversationStore()))
    serve(
        entities=[agent],
        host="127.0.0.1",
        port=int(os.environ.get("DEVUI_PORT", "8090")),
        auto_open=os.environ.get("DEVUI_OPEN", "1") == "1",
    )


if __name__ == "__main__":
    main()
