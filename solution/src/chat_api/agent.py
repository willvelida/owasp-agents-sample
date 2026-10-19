"""Biotrackr chat agent."""

import os
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from agent_framework import Agent, AgentSession, ContextProvider, MCPStreamableHTTPTool, SessionContext
from agent_framework.foundry import FoundryChatClient

from auth_common.azure_credential import azure_credential
from chat_api.auth import Principal, current_principal
from chat_api.history import CosmosHistoryProvider
from chat_api.identity import DownstreamTokenProvider, mcp_authorization, mcp_headers
from chat_api.prompts import SYSTEM_PROMPT

PrincipalFallback = Callable[[], Awaitable[Principal]]


class IdentityProvider(ContextProvider):
    """Binds each run to the signed-in user and fetches the OBO token the MCP tool will send.

    ASI03: fails closed. With no authenticated principal, or if the OBO exchange fails, the run stops
    before the model is called.
    """

    def __init__(self, tokens: DownstreamTokenProvider, fallback: PrincipalFallback | None = None) -> None:
        super().__init__("identity")
        self._tokens = tokens
        self._fallback = fallback

    async def before_run(
        self, *, agent: Any, session: AgentSession, context: SessionContext, state: dict[str, Any]
    ) -> None:
        principal = current_principal.get()
        if principal is None and self._fallback is not None:
            principal = await self._fallback()
            current_principal.set(principal)
        if principal is None:
            raise PermissionError("no authenticated user")
        mcp_authorization.set(await self._tokens.health_mcp_header(principal))
        context.extend_instructions(
            self.source_id,
            f"The signed-in user is {principal.name or 'the user'}. Today is {date.today().isoformat()}. "
            "Your tools only ever return the signed-in user's own data.",
        )


def build_agent(
    history: CosmosHistoryProvider,
    tokens: DownstreamTokenProvider | None = None,
    principal_fallback: PrincipalFallback | None = None,
) -> Agent:
    # ASI03: Entra only (managed identity on Azure, az login locally); the Foundry resource has key auth disabled.
    client = FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ.get("FOUNDRY_MODEL", "gpt-4.1"),
        credential=azure_credential(),
    )
    # ASI03: the MCP tool sends the per-run OBO token from IdentityProvider.
    # ASI02 (starter): no allowed_tools, so every tool on the server (including delete_records) is exposed.
    # ASI08 (starter): no request timeout.
    health = MCPStreamableHTTPTool(
        name="health",
        url=os.environ.get("MCP_URL", "http://localhost:8001/mcp"),
        header_provider=mcp_headers,
    )
    return Agent(
        client=client,
        name="BiotrackrChatAgent",
        instructions=SYSTEM_PROMPT,
        tools=[health],
        context_providers=[IdentityProvider(tokens or DownstreamTokenProvider(), principal_fallback), history],
    )
