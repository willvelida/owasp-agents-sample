"""Biotrackr chat agent."""

import os
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from agent_framework import Agent, AgentSession, ContextProvider, SessionContext
from agent_framework.foundry import FoundryChatClient

from auth_common.azure_credential import azure_credential
from chat_api.auth import Principal, current_principal
from chat_api.history import CosmosHistoryProvider
from chat_api.identity import DownstreamTokenProvider, mcp_authorization, mcp_headers
from chat_api.mcp_pinning import PinnedMCPStreamableHTTPTool
from chat_api.middleware import build_middleware, load_governance
from chat_api.prompts import load_system_prompt
from governance import PolicyError, descriptors

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
    # ASI01: hash-pinned prompt; ASI02: versioned governance policy. Either failing stops startup.
    instructions = load_system_prompt()
    try:
        governance = load_governance()
        pinned = descriptors.load_lock()
        middleware = build_middleware(governance)
    except PolicyError as exc:
        raise SystemExit(f"governance policy unavailable: {exc}") from exc
    # ASI03: Entra only (managed identity on Azure, az login locally); the Foundry resource has key auth disabled.
    client = FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ.get("FOUNDRY_MODEL", "gpt-4.1"),
        credential=azure_credential(),
    )
    # ASI03: the MCP tool sends the per-run OBO token from IdentityProvider.
    # ASI02: only the allowlisted read tools are exposed to the model.
    # ASI04: descriptors are checked against policies/mcp_tools.lock.json on every tools/list.
    # ASI08 (starter): no request timeout.
    health = PinnedMCPStreamableHTTPTool(
        name="health",
        url=os.environ.get("MCP_URL", "http://localhost:8001/mcp"),
        header_provider=mcp_headers,
        allowed_tools=governance.allowed_tools,
        pinned=pinned,
    )
    # ASI01, ASI02: governance middleware lives on the Agent, so DevUI runs are governed as well.
    return Agent(
        client=client,
        name="BiotrackrChatAgent",
        instructions=instructions,
        tools=[health],
        middleware=middleware,
        context_providers=[IdentityProvider(tokens or DownstreamTokenProvider(), principal_fallback), history],
    )
