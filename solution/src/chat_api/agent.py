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
from chat_api.middleware.output_guard import CLASSIFIER_INSTRUCTIONS, OutputGuard, model_classifier
from chat_api.prompts import load_system_prompt
from chat_api.tools_report import ReportService, build_report_tools
from governance import PolicyError, descriptors

PrincipalFallback = Callable[[], Awaitable[Principal]]


class BiotrackrAgent(Agent):
    """Agent that tolerates AG-UI passing connected MCP functions back in as run tools.

    With an approval-required tool, ag-ui 1.6.0 passes every server tool as `tools=`, including the functions
    of a connected MCP tool; MAF 1.22.0 then appends the same MCP functions again and fails every run with a
    duplicate tool name. The agent adds its MCP functions itself, so they are dropped from the run's tools.
    """

    def run(self, messages: Any = None, *, tools: Any = None, **kwargs: Any) -> Any:
        if isinstance(tools, list) and self.mcp_tools:
            # By name: an MCP tool reloads its functions (new objects) when the per-run OBO header changes.
            own = {f.name for mcp in self.mcp_tools for f in getattr(mcp, "functions", [])}
            tools = [t for t in tools if getattr(t, "name", None) not in own]
        return super().run(messages, tools=tools, **kwargs)


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
    tokens = tokens or DownstreamTokenProvider()
    # ASI03: Entra only (managed identity on Azure, az login locally); the Foundry resource has key auth disabled.
    client = FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ.get("FOUNDRY_MODEL", "gpt-4.1"),
        credential=azure_credential(),
    )
    # ASI09: a separate, tool-less client classifies every reply before it is released.
    classifier_client = FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ.get("FOUNDRY_MODEL", "gpt-4.1"),
        credential=azure_credential(),
    )
    output_guard = OutputGuard(
        model_classifier(
            lambda: Agent(client=classifier_client, name="OutputPolicy", instructions=CLASSIFIER_INSTRUCTIONS)
        )
    )
    try:
        governance = load_governance()
        pinned = descriptors.load_lock()
        middleware = build_middleware(governance, output_guard=output_guard)
    except PolicyError as exc:
        raise SystemExit(f"governance policy unavailable: {exc}") from exc
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
    # ASI07, ASI09: report tools need approval, carry an app-only report API token, and are typed.
    reports = build_report_tools(ReportService(tokens), approval_required=governance.approval_required)
    return BiotrackrAgent(
        client=client,
        name="BiotrackrChatAgent",
        instructions=instructions,
        tools=[health, *reports],
        middleware=middleware,
        context_providers=[IdentityProvider(tokens, principal_fallback), history],
    )
