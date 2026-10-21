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
from chat_api.mcp_pool import UserMCPTool, UserMCPTools, current_user_mcp_tool
from chat_api.middleware import build_middleware, load_governance
from chat_api.middleware.audit import AuditTrail, CosmosAuditSink
from chat_api.middleware.output_guard import CLASSIFIER_INSTRUCTIONS, OutputGuard, model_classifier
from chat_api.middleware.resilience import CircuitBreaker, harden_model_client
from chat_api.prompts import load_system_prompt
from chat_api.tools_report import ReportService, build_report_tools
from governance import PolicyError, descriptors

PrincipalFallback = Callable[[], Awaitable[Principal]]


class BiotrackrAgent(Agent):
    """Agent whose health MCP tool is the signed-in user's own (ASI08 bulkhead, chat_api.mcp_pool).

    `mcp_tools` is the tool IdentityProvider acquired for this run. It also tolerates AG-UI passing MCP functions
    back in as run tools: with an approval-required tool, ag-ui 1.6.0 passes every server tool as `tools=`,
    including connected MCP functions; MAF 1.22.0 then appends the same MCP functions again and fails every run
    with a duplicate tool name. The agent adds its MCP functions itself, so they are dropped from the run's tools.
    """

    def __init__(self, *args: Any, user_tools: UserMCPTools | None = None, **kwargs: Any) -> None:
        self.user_tools = user_tools
        self._static_mcp_tools: list[Any] = []
        super().__init__(*args, **kwargs)

    @property
    def mcp_tools(self) -> list[Any]:
        user_tool = current_user_mcp_tool.get() if self.user_tools is not None else None
        return [*self._static_mcp_tools, *([user_tool] if user_tool is not None else [])]

    @mcp_tools.setter
    def mcp_tools(self, value: list[Any]) -> None:
        self._static_mcp_tools = list(value)

    def run(self, messages: Any = None, *, tools: Any = None, **kwargs: Any) -> Any:
        if isinstance(tools, list):
            # By name: an MCP tool reloads its functions (new objects) when the per-run OBO header changes.
            own = {f.name for mcp in self._static_mcp_tools for f in getattr(mcp, "functions", [])}
            if self.user_tools is not None:
                own |= self.user_tools.function_names
            tools = [t for t in tools if getattr(t, "name", None) not in own]
        return super().run(messages, tools=tools, **kwargs)


class IdentityProvider(ContextProvider):
    """Binds each run to the signed-in user and fetches the OBO token the MCP tool will send.

    ASI03: fails closed. With no authenticated principal, or if the OBO exchange fails, the run stops
    before the model is called. ASI08: connects the user's own health MCP tool for the run.
    """

    def __init__(
        self,
        tokens: DownstreamTokenProvider,
        fallback: PrincipalFallback | None = None,
        user_tools: UserMCPTools | None = None,
    ) -> None:
        super().__init__("identity")
        self._tokens = tokens
        self._fallback = fallback
        self._user_tools = user_tools

    async def before_run(
        self, *, agent: Any, session: AgentSession, context: SessionContext, state: dict[str, Any]
    ) -> None:
        current_user_mcp_tool.set(None)
        principal = current_principal.get()
        if principal is None and self._fallback is not None:
            principal = await self._fallback()
            current_principal.set(principal)
        if principal is None:
            raise PermissionError("no authenticated user")
        mcp_authorization.set(await self._tokens.health_mcp_header(principal))
        if self._user_tools is not None:
            await self._user_tools.acquire(principal.oid)
        context.extend_instructions(
            self.source_id,
            f"The signed-in user is {principal.name or 'the user'}. Today is {date.today().isoformat()}. "
            "Your tools only ever return the signed-in user's own data.",
        )


def build_agent(
    history: CosmosHistoryProvider,
    tokens: DownstreamTokenProvider | None = None,
    principal_fallback: PrincipalFallback | None = None,
    *,
    audit: AuditTrail | None = None,
) -> Agent:
    # ASI01: hash-pinned prompt; ASI02: versioned governance policy. Either failing stops startup.
    instructions = load_system_prompt()
    tokens = tokens or DownstreamTokenProvider()
    # ASI10: one hash-chained audit trail (Cosmos DB audit container) for AGT and the solution's own controls.
    audit = audit or AuditTrail(CosmosAuditSink())
    # ASI03: Entra only (managed identity on Azure, az login locally); the Foundry resource has key auth disabled.
    # ASI08: connect 5 s, read 30 s, at most 2 jittered retries, and a bounded tool loop.
    client = harden_model_client(
        FoundryChatClient(
            project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
            model=os.environ.get("FOUNDRY_MODEL", "gpt-4.1"),
            credential=azure_credential(),
        )
    )
    # ASI09: a separate, tool-less client classifies every reply before it is released.
    classifier_client = harden_model_client(
        FoundryChatClient(
            project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
            model=os.environ.get("FOUNDRY_MODEL", "gpt-4.1"),
            credential=azure_credential(),
        )
    )
    output_guard = OutputGuard(
        model_classifier(
            lambda: Agent(client=classifier_client, name="OutputPolicy", instructions=CLASSIFIER_INSTRUCTIONS)
        )
    )
    try:
        governance = load_governance()
        pinned = descriptors.load_lock()
        middleware = build_middleware(governance, output_guard=output_guard, audit=audit)
    except PolicyError as exc:
        raise SystemExit(f"governance policy unavailable: {exc}") from exc
    # ASI03: the MCP tool sends the per-run OBO token from IdentityProvider.
    # ASI02: only the allowlisted read tools are exposed to the model.
    # ASI04: descriptors are checked against policies/mcp_tools.lock.json on every tools/list.
    # ASI08: deadlines, jittered retries, and a circuit breaker; an outage gives a "try again" reply. Each user has
    # their own MCP session (bulkhead); the breaker is shared because it describes the server.
    breaker = CircuitBreaker("health-mcp", audit=audit)
    mcp_url = os.environ.get("MCP_URL", "http://localhost:8001/mcp")
    user_tools = UserMCPTools(
        lambda oid: UserMCPTool(
            name="health",
            url=mcp_url,
            header_provider=mcp_headers,
            allowed_tools=governance.allowed_tools,
            pinned=pinned,
            breaker=breaker,
            owner=oid,
        ),
        function_names=governance.allowed_tools,
    )
    # ASI01, ASI02: governance middleware lives on the Agent, so DevUI runs are governed as well.
    # ASI07, ASI09: report tools need approval, carry an app-only report API token, and are typed.
    # ASI08: the report agent has its own circuit breaker.
    reports = build_report_tools(
        ReportService(tokens, breaker=CircuitBreaker("report-agent", audit=audit)),
        approval_required=governance.approval_required,
    )
    return BiotrackrAgent(
        client=client,
        name="BiotrackrChatAgent",
        instructions=instructions,
        tools=list(reports),
        user_tools=user_tools,
        # ASI08: every reply is bounded.
        default_options={"max_tokens": governance.max_output_tokens},
        middleware=middleware,
        context_providers=[IdentityProvider(tokens, principal_fallback, user_tools), history],
    )
