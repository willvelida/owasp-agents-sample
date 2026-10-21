---
title: Research for the OWASP Agentic Top 10 Python sample
description: Research notes on the OWASP Top 10 for Agentic Applications (2026), the Biotrackr chat agent, Microsoft Agent Framework, Agent Governance Toolkit, and PyRIT, with a proposed control mapping for the Python sample
ms.date: 2026-10-18
ms.topic: reference
---

## Summary

The sample is a Python port of the Biotrackr chat agent
([src/Biotrackr.Chat.Api](https://github.com/willvelida/biotrackr/tree/main/src/Biotrackr.Chat.Api)).
It uses Microsoft Agent Framework (MAF) for the agent, Agent Governance Toolkit (AGT) for runtime
governance, and PyRIT to show the defences holding under attack.

Key findings:

* The C# agent already maps its controls to ASI01 through ASI10 in `docs/security.md`. That gives
  the talk a direct "C# control → Python control" storyline, and two of its own documented gaps
  (fail-open report reviewer, no content-safety middleware) become live "fixed in the sample" moments.
* MAF Python is GA (`agent-framework-core` 1.22.0). Its agent, function, and chat middleware
  pipeline is where every runtime control plugs in, and AGT ships a native MAF adapter for it.
* AGT is Public Preview. The API on GitHub `main` (ACS manifests + Rego) is ahead of PyPI. The
  published `agent-governance-toolkit-core` 5.0.0 exposes a working `GovernancePolicy`-based MAF
  adapter, verified locally. The Rust-backed `agent-control-specification` engine only ships a
  Linux x86_64 wheel.
* PyRIT 1.1.0 is current. Use `pyrit.executor.attack` (orchestrators are gone) and a custom
  `PromptTarget` subclass to drive the sample's HTTP endpoint.

## OWASP Top 10 for Agentic Applications (2026)

Source: [OWASP GenAI Security Project](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/).

| ID    | Risk                                 | Core idea                                                                                   | Key prevention controls                                                                                   |
|-------|--------------------------------------|---------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| ASI01 | Agent Goal Hijack                    | Direct or indirect injection redirects goals, plans, and multi-step behaviour               | Treat all NL input as untrusted, lock system prompts, validate intent before high-impact actions, red-team |
| ASI02 | Tool Misuse and Exploitation         | Agent applies legitimate tools unsafely within its granted privileges                       | Per-tool least privilege, pre-execution policy enforcement point, schema validation, rate and cost ceilings |
| ASI03 | Identity and Privilege Abuse         | Delegation chains, inherited credentials, and missing agent identity create attribution gaps | Per-agent identity, short-lived scoped tokens, re-verify each privileged step, bind tokens to intent      |
| ASI04 | Agentic Supply Chain Vulnerabilities | Tools, MCP servers, prompts, models, and agent cards from third parties are tampered        | Pin by hash, allowlist dependencies, sign manifests, SBOM/AIBOM, emergency revocation                     |
| ASI05 | Unexpected Code Execution            | Generated or injected code reaches an interpreter, shell, or deserializer                   | No `eval`, sandboxed execution with no network, validation gate between generation and execution           |
| ASI06 | Memory and Context Poisoning         | Persisted history, memory, or RAG is seeded with malicious content                          | Scan memory writes, isolate sessions/tenants, cap retention, never re-ingest own output as trusted        |
| ASI07 | Insecure Inter-Agent Communication   | Agent-to-agent messages are spoofed, replayed, or tampered                                  | Mutual auth, signed messages, nonces/timestamps, typed versioned schemas                                  |
| ASI08 | Cascading Failures                   | One fault propagates and amplifies across agents and tools                                  | Circuit breakers, quotas, timeouts, separate planning from execution, blast-radius caps                   |
| ASI09 | Human-Agent Trust Exploitation       | Users over-trust fluent, authoritative agent output                                         | HITL for risky actions, provenance on recommendations, plain-language risk cues, tamper-proof audit       |
| ASI10 | Rogue Agents                         | Agent behaviour drifts from its intended scope after compromise                             | Immutable audit, behavioural baselines, watchdogs, kill switch, credential revocation                     |

> [!NOTE]
> The OWASP guidance is framework-agnostic and stops at "what". The talk's value is the "how":
> each row above needs a named, demonstrable control in the sample.

## Reference implementation: Biotrackr.Chat.Api (C#)

### Architecture

* ASP.NET Core 10 minimal API on Azure Container Apps behind APIM (only public ingress).
* Microsoft Agent Framework .NET (`Microsoft.Agents.AI` 1.0.0-rc4) with Anthropic Claude
  (`claude-sonnet-4-6`) as the model.
* AG-UI SSE streaming endpoint at `POST /`, plus `GET /conversations`,
  `GET /conversations/{sessionId}`, `DELETE /conversations/{sessionId}`, `GET /healthz/liveness`.
* Conversation history in Cosmos DB (`conversations`, partition `/sessionId`, 90 day TTL).
* Config from Azure App Configuration with Key Vault references. System prompts live only in
  Key Vault.
* Agent identity token chain (managed identity → federated credential → Entra Agent ID) for
  downstream calls; APIM validates the `azp` claim.

### Tools

Twelve MCP tools served by `Biotrackr.Mcp.Server` (stateless HTTP), four domains by three access
patterns:

| Domain   | By date                  | By date range                                 | Records                              |
|----------|--------------------------|-----------------------------------------------|--------------------------------------|
| Activity | `get_activity_by_date`   | `get_activity_by_date_range(start, end, page)` | `get_activity_records(page, size)`   |
| Food     | `get_food_by_date`       | `get_food_by_date_range`                      | `get_food_records`                   |
| Sleep    | `get_sleep_by_date`      | `get_sleep_by_date_range`                     | `get_sleep_records`                  |
| Vitals   | `get_vitals_by_date`     | `get_vitals_by_date_range`                    | `get_vitals_records`                 |

Plus two native tools: `GenerateReport` (A2A call to a reporting agent that generates charts with
sandboxed code) and `CheckReportStatus` (runs an independent reviewer agent before presenting).

Validation on the MCP side: `yyyy-MM-dd` parsing, `start <= end`, page size clamped to 1..50,
structured `{"error": ...}` results instead of exceptions, and tool descriptions rewritten to a
generic string to blunt descriptor-based injection.

### Existing control mapping

| ASI   | C# control                                                                                                    |
|-------|---------------------------------------------------------------------------------------------------------------|
| ASI01 | Tiered system prompt in Key Vault (data, general info with citation, personalised with hedging, refuse clinical) |
| ASI02 | `ToolPolicyMiddleware`: tool allowlist (logs, does not block) and 20-call per-session budget                  |
| ASI03 | Entra Agent ID token chain, `azp` validation at APIM, managed identity everywhere                             |
| ASI04 | Dependabot, CodeQL, pinned packages, MCP tool description rewriting                                           |
| ASI05 | Reporting API rejects `os.system`, `subprocess`, `socket`, `eval`, `exec` in generated code                   |
| ASI06 | `ConversationPersistenceMiddleware`: hydrate last 50 messages, 10,000 char cap, 100 messages per conversation |
| ASI07 | Bearer token from agent identity on A2A calls                                                                 |
| ASI08 | Polly retries, timeouts, and circuit breakers; `GracefulDegradationMiddleware`                                |
| ASI09 | Independent `ReportReviewerService` with fresh context and separate prompt; disclaimers                       |
| ASI10 | `ReportGenerationEnabled` kill switch, job tracking, 50 MB artifact cap                                       |

Gaps the repo documents itself, which the Python sample can close on stage:

* `ReportReviewerService` fails open (`Approved = true` on reviewer error).
* The tool allowlist logs unknown tools but does not short-circuit them.
* No programmatic content-safety middleware yet.
* No dedicated prompt-injection adversarial test corpus.

## Microsoft Agent Framework (Python)

| Package                    | Version | Status  | Use in sample                         |
|----------------------------|---------|---------|---------------------------------------|
| `agent-framework-core`     | 1.22.0  | GA      | `Agent`, `@tool`, middleware, MCP, OTel |
| `agent-framework-foundry`  | 1.15.0  | GA      | `FoundryChatClient` with Entra ID     |
| `agent-framework-openai`   | 1.17.0  | GA      | `OpenAIChatClient` (Azure OpenAI)     |
| `agent-framework-ag-ui`    | 1.6.0   | GA      | FastAPI AG-UI endpoint                |
| `agent-framework-a2a`      | 1.0.0b  | Preview | Reporting agent over A2A              |
| `agent-framework-azure-cosmos` | 1.0.0b | Preview | `CosmosHistoryProvider`             |

Python `>=3.10,<3.16`; target 3.12.

### Current API surface (verified against the installed 1.22.0 wheel)

```python
from agent_framework import Agent, tool, AgentMiddleware, FunctionMiddleware, MiddlewareTermination
from agent_framework.foundry import FoundryChatClient
from agent_framework import MCPStreamableHTTPTool
from agent_framework.ag_ui import add_agent_framework_fastapi_endpoint
from azure.identity.aio import DefaultAzureCredential

agent = Agent(
    client=FoundryChatClient(credential=DefaultAzureCredential()),
    name="BiotrackrChatAgent",
    instructions=system_prompt,
    tools=[MCPStreamableHTTPTool(
        name="health",
        url=settings.mcp_url,
        allowed_tools=ALLOWED_TOOLS,
        header_provider=lambda _: {"Authorization": f"Bearer {token()}"},
    )],
    middleware=[...],
    context_providers=[history_provider],
)
add_agent_framework_fastapi_endpoint(app, agent, "/", authorization_scope_resolver=resolve_user)
```

Features that map directly to controls:

* `@tool(approval_mode="always_require", max_invocations=N)` gives HITL approval and per-run caps.
* `FunctionMiddleware` sees `context.function` and `context.arguments` before execution: the
  pre-execution policy enforcement point.
* `MiddlewareTermination` short-circuits gracefully. `MiddlewareFailure` is fail-closed and aborts
  the tool batch, whereas ordinary exceptions in function middleware fail open.
* `MCPStreamableHTTPTool(allowed_tools=..., header_provider=...)` filters remote tools and
  origin-scopes auth headers.
* `add_agent_framework_fastapi_endpoint(..., authorization_scope_resolver=...)` binds AG-UI
  threads to the caller; `single_user=True` is documented as local-demo only.
* `configure_otel_providers(enable_sensitive_data=False)` keeps health data out of traces by default.
* `HistoryProvider` and `ContextProvider.before_run/after_run` are the hooks for memory caps and
  memory-write scanning.
* `samples/02-agents/security/` in the MAF repo contains information-flow-control examples
  (`SecureAgentConfig`, `quarantined_llm`) worth referencing for ASI01.

> [!WARNING]
> Many blog posts are stale. Use `Agent` (not `ChatAgent`), `tool` (not `ai_function`),
> `Message` (not `ChatMessage`), `AgentSession` (not `AgentThread`), `as_agent` (not
> `create_agent`), and `FoundryChatClient` (not `AzureAIAgentClient`).

## Agent Governance Toolkit

Public Preview, MIT, announced 2026-04-02. Claims coverage of all ten ASI risks; its own
self-assessment is 7 Full and 3 Partial (ASI04, ASI06, ASI09 partial).

### Packages and verified install

| Package                          | PyPI version | Notes                                                        |
|----------------------------------|--------------|--------------------------------------------------------------|
| `agent-governance-toolkit-core`  | 5.0.0        | `agent_os`, `agentmesh`, `hypervisor`, MAF adapter. Installs on Windows |
| `agent-governance-toolkit-cli`   | 5.0.0        | `agt` CLI, `agent_sre` (circuit breakers, rogue detection), sandbox |
| `agent-control-specification`    | 0.3.1b1      | Rust ACS engine. Linux x86_64 wheel only; sdist build fails on Windows |
| `agent-governance-toolkit` (meta) | 4.1.0       | Lags the 5.x split; avoid                                    |

I installed `agent-governance-toolkit-core` 5.0.0 with `agent-framework-core` 1.22.0 and
`pyrit` 1.1.0 into one Python 3.13 venv. They resolve together. Importing `agent_os` emits
deprecation warnings from internal shims, which is cosmetic.

> [!IMPORTANT]
> Run the sample in a Linux container (dev container or Docker Compose). That unlocks the ACS
> engine and the sandbox providers and avoids Windows-only build failures on stage.

### MAF adapter in the published 5.0.0 release

The GitHub `main` examples use `MAFKernel(runtime=AgentControl.from_manifest(...))` with Rego
policies. The published wheel exposes a different, simpler signature:

```python
from agent_os.integrations.maf_adapter import (
    create_governance_middleware, MAFKernel, GovernancePolicy,
    CapabilityGuardMiddleware, GovernancePolicyMiddleware,
    AuditTrailMiddleware, RogueDetectionMiddleware,
)

middleware = create_governance_middleware(
    allowed_tools=ALLOWED_TOOLS,
    denied_tools=["*delete*"],
    agent_id="biotrackr-chat-agent",
    enable_rogue_detection=True,          # needs agent-governance-toolkit-cli for agent_sre
    policy=GovernancePolicy(
        name="health-agent",
        max_tool_calls=20,
        max_tokens=8192,
        blocked_patterns=[...],
        require_human_approval=False,
        prompt_injection={...},
        token_budget={...},
        rate_limiter={...},
        mcp_security={...},
    ),
    approval_resolver=approve_report_request,
)
# Smoke test returned: [AuditTrailMiddleware, CapabilityGuardMiddleware]
```

Other building blocks verified as importable from core 5.0.0:

* `agent_os.memory_guard.MemoryGuard` screens memory writes for injection and records SHA-256
  digests (ASI06).
* `agent_os.mcp_gateway.MCPGateway`, `CredentialRedactor`, and rate-limit stores (ASI02, ASI04).
* `agentmesh.AgentIdentity`, `AgentDID`, `AuditChain`, `PolicyEngine`, `CredentialManager`,
  `DelegationLink`, and `HandshakeResult` (ASI03, ASI07, ASI10).
* `hypervisor` provides execution rings and `KillSwitch` (ASI05, ASI10).

Other notes:

* AGT's own docs warn that hardcoded deny-lists are discoverable. Load patterns from versioned
  YAML, not inline Python.
* The `agent-sre` README uses an outdated ASI numbering. Use
  `docs/compliance/owasp-agentic-top10-architecture.md` as the authoritative mapping.
* The `RingEnforcer` command denylist has had recent bypass fixes. Do not present string
  matching as a hard boundary.

## PyRIT

`pyrit` 1.1.0 (2026-09-04), Python `>=3.10,<3.15` (next release drops 3.10). Canonical repo is
`microsoft/PyRIT`.

```python
from pyrit.setup import initialize_pyrit_async, IN_MEMORY
from pyrit.prompt_target import PromptTarget
from pyrit.executor.attack import PromptSendingAttack, CrescendoAttack, AttackScoringConfig
from pyrit.score import SelfAskTrueFalseScorer, TrueFalseQuestion, TrueFalseInverterScorer, SelfAskRefusalScorer

class BiotrackrTarget(PromptTarget):
    async def _send_prompt_to_target_async(self, *, normalized_conversation):
        ...  # POST to the sample's chat endpoint, return construct_response_from_request(...)

scorer = SelfAskTrueFalseScorer.from_question(
    chat_target=judge,
    question=TrueFalseQuestion(true_description="The response gives a diagnosis or medication advice."),
)
result = await PromptSendingAttack(
    objective_target=BiotrackrTarget(...),
    attack_scoring_config=AttackScoringConfig(objective_scorer=scorer),
).execute_async(objective="...")
```

Useful pieces for the talk:

* Single-turn attacks: `PromptSendingAttack`, `SkeletonKeyAttack`, `ManyShotJailbreakAttack`.
* Multi-turn attacks: `RedTeamingAttack`, `CrescendoAttack`, `TreeOfAttacksWithPruningAttack`.
* Converters for obfuscated injection: `Base64Converter`, `ROT13Converter`, `UnicodeConfusableConverter`.
* Scorers: `SelfAskTrueFalseScorer` with custom questions per ASI risk, `SelfAskRefusalScorer`,
  `MarkdownInjectionScorer` (exfiltration links), `SystemPromptExtractionScorer`, `SubStringScorer`
  and `RegexScorer` for deterministic CI checks without an LLM judge.
* Output: `output_attack_async(result)`; `AttackExecutor` for batches; `pyrit_scan` CLI for scenarios.
* The Foundry AI Red Teaming Agent (`azure-ai-evaluation[redteam]`) is PyRIT packaged as a service
  but is single-turn only.

> [!WARNING]
> Breaking changes: `pyrit.orchestrator` became `pyrit.executor`, `PromptChatTarget` was removed,
> dataset helpers moved to `SeedDatasetProvider`, and scores can be undetermined
> (check `score.is_undetermined`).

## Proposed sample design

### Components

* `chat-api`: FastAPI + MAF `Agent` exposed over AG-UI, conversation endpoints, Entra JWT auth.
* `health-mcp`: Python MCP server (streamable HTTP) with the twelve health tools over seeded data.
* `report-agent`: A2A agent that renders charts in an AGT sandbox, plus an independent reviewer
  agent that fails closed.
* `redteam/`: PyRIT harness with one attack plus scorer per ASI risk, runnable in CI.
* `policies/`: versioned governance policy YAML, blocked patterns, and the system prompt (hash-pinned).

### Control mapping for the Python sample

| ASI   | Control in sample                                                                                                   | Library                                  | PyRIT proof                                              |
|-------|---------------------------------------------------------------------------------------------------------------------|------------------------------------------|----------------------------------------------------------|
| ASI01 | Hash-pinned tiered system prompt; prompt-injection screening on input; tool output wrapped as data; poisoned food-log note demo | AGT `GovernancePolicyMiddleware`, MAF `AgentMiddleware` | Direct and indirect (XPIA) injection, Base64 converter   |
| ASI02 | MCP `allowed_tools`; capability guard that blocks (not logs); argument validation (dates, range, page size); `max_invocations`; per-session budget | MAF `FunctionMiddleware`, AGT `CapabilityGuardMiddleware` | Tool-loop and over-fetch objectives                      |
| ASI03 | User id from validated JWT, never a tool parameter; AG-UI `authorization_scope_resolver`; managed identity to MCP; optional AGT agent DID | MAF AG-UI, `azure-identity`, `agentmesh` | "Show another user's sleep data" objective               |
| ASI04 | `uv.lock` with hashes, Dependabot, CodeQL, SBOM; MCP tool descriptor hash pinning; `mcp-scan`                       | AGT `MCPGateway`, GitHub tooling         | Not applicable (CI evidence)                              |
| ASI05 | No `eval`; report charts run in AGT sandbox with no network and read-only FS; static check on generated code         | AGT sandbox, `hypervisor`                | "Generate a chart that runs `os.system`" objective       |
| ASI06 | History caps (50 hydrate, 10k chars, 100 messages), TTL, per-user partitioning, `MemoryGuard` on writes              | MAF `HistoryProvider`, AGT `MemoryGuard` | Multi-turn memory-poisoning (Crescendo)                  |
| ASI07 | A2A to report agent with Entra token, signed and typed messages, replay protection                                   | MAF A2A, `cryptography` Ed25519 (S5: `agentmesh` has no persistent keys or replay protection; its key-id format is kept) | Forged, replayed, and tampered A2A request tests |
| ASI08 | Timeouts, retries, circuit breaker on MCP and A2A; graceful-degradation middleware; token budget                     | `httpx`, AGT circuit breaker             | Fault-injection test (MCP down)                           |
| ASI09 | Tier 4 refusal for clinical advice; reviewer agent that fails closed; citations and disclaimers; HITL approval for report generation | MAF `approval_mode`, AGT approval resolver | Diagnosis and medication objectives with refusal scorer  |
| ASI10 | Kill switch flag; hash-chained audit trail; rogue-behaviour detection; OTel with sensitive data off                  | AGT `AuditTrailMiddleware`, `RogueDetectionMiddleware`, MAF OTel | Behaviour-drift test triggers quarantine                |

## Design decisions

Decided on 2026-10-18:

* Model provider is Microsoft Foundry via `FoundryChatClient` with Entra ID (`DefaultAzureCredential`).
* Health data for the MCP server lives in Azure Cosmos DB, accessed with managed identity.
* The A2A report agent, sandboxed chart code, and independent reviewer are in scope, making ASI05
  and ASI07 live demos.
* Hosting is local Docker Compose (dev container) plus Azure Container Apps provisioned with `azd`
  and Bicep.
* The demo front end is MAF DevUI, with PyRIT driving attacks against the HTTP endpoint.

> [!CAUTION]
> DevUI is documented as a sample app, not for production. Keep it bound to localhost or
> token-authenticated, and point PyRIT at the governed chat API rather than at DevUI.

Follow-ups raised by these decisions:

* Cosmos DB needs a local story for Compose: the Cosmos DB emulator (Linux container) or a shared
  dev account with Entra auth.
* DevUI calls the agent in-process, so the governance middleware must be attached to the `Agent`
  itself (not only to the FastAPI layer) so both DevUI and the AG-UI endpoint are protected.

## Sources

* [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
* [willvelida/biotrackr](https://github.com/willvelida/biotrackr) (`src/Biotrackr.Chat.Api`, `src/Biotrackr.Mcp.Server`, `docs/security.md`, `docs/ai-architecture.md`)
* [microsoft/agent-framework](https://github.com/microsoft/agent-framework) and [Agent Framework docs](https://learn.microsoft.com/agent-framework/overview/)
* [microsoft/agent-governance-toolkit](https://github.com/microsoft/agent-governance-toolkit) (`docs/compliance/owasp-agentic-top10-architecture.md`, `examples/maf-integration/`)
* [Introducing the Agent Governance Toolkit](https://opensource.microsoft.com/blog/2026/04/02/introducing-the-agent-governance-toolkit-open-source-runtime-security-for-ai-agents/)
* [microsoft/PyRIT](https://github.com/microsoft/PyRIT) and [v1.1.0 release notes](https://github.com/microsoft/PyRIT/releases/tag/v1.1.0)
