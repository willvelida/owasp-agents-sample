"""Biotrackr chat agent."""

import os
from datetime import date
from typing import Any

from agent_framework import Agent, AgentSession, ContextProvider, MCPStreamableHTTPTool, SessionContext
from agent_framework.openai import OpenAIChatClient

from chat_api.history import CosmosHistoryProvider, current_user
from chat_api.prompts import SYSTEM_PROMPT


class CurrentUserProvider(ContextProvider):
    """Tells the model who the user is and what day it is."""

    def __init__(self) -> None:
        super().__init__("current_user")

    async def before_run(
        self, *, agent: Any, session: AgentSession, context: SessionContext, state: dict[str, Any]
    ) -> None:
        # ASI03 (starter): the user id is whatever the client claimed, and the model is trusted to pass it on.
        context.extend_instructions(
            self.source_id,
            f"The current user's id is '{current_user.get()}'. Today is {date.today().isoformat()}.",
        )


def build_agent(history: CosmosHistoryProvider) -> Agent:
    client = OpenAIChatClient(
        model=os.environ.get("FOUNDRY_MODEL", "gpt-4.1"),
        azure_endpoint=os.environ["FOUNDRY_ENDPOINT"],
        # ASI03 (starter): static API key instead of a managed or agent identity.
        api_key=os.environ["FOUNDRY_API_KEY"],
    )
    # ASI02 (starter): no allowed_tools, so every tool on the server (including delete_records) is exposed.
    # ASI08 (starter): no request timeout.
    health = MCPStreamableHTTPTool(name="health", url=os.environ.get("MCP_URL", "http://localhost:8001/mcp"))
    return Agent(
        client=client,
        name="BiotrackrChatAgent",
        instructions=SYSTEM_PROMPT,
        tools=[health],
        context_providers=[CurrentUserProvider(), history],
    )
