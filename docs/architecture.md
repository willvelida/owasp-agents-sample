---
title: Architecture
description: Architecture of the OWASP Agentic Top 10 sample, covering the insecure starter, the secured solution, identity flow, control placement, and Azure deployment
ms.date: 2026-10-23
ms.topic: concept
---

## Overview

The sample is a Python port of the Biotrackr chat agent, shipped as two stacks with the same components and file names:

* `starter/` runs locally only and leaves every OWASP Agentic risk exploitable ([ADR-0003](adr/0003-mirrored-starter-and-solution.md), [ADR-0004](adr/0004-naive-but-plausible-starter.md), [ADR-0005](adr/0005-starter-local-only-solution-on-azure.md))
* `solution/` applies a control for each risk and runs locally or on Azure Container Apps

Both stacks share the seed data, the command-line client, and the PyRIT red-team harness at the repository root. The solution also has a text-only browser client in `solution/ui` ([ADR-0025](adr/0025-browser-chat-client.md)).

## Repository layout

```text
.devcontainer/      Optional dev container (Podman); primary workflow is host uv + podman compose
data/seed/          alice and bob health data, poisoned food note, canaries
client/             CLI AG-UI client (--as alice|bob, --target starter|solution-local|solution-azure)
redteam/            PyRIT harness and scorers shared by both stacks
starter/            Insecure stack (Podman Compose only)
solution/           Secured stack (Podman Compose, azd, Bicep)
  policies/         Hash-pinned system prompt, governance YAML, blocked patterns, MCP descriptor lock
  scripts/          Agent ID provisioning and seeding
  infra/            Bicep for Azure Container Apps
  ui/               Text-only Vue browser client for the solution (MSAL sign-in, nginx image)
docs/adr/           Architecture decision records
```

## Starter components

The starter trusts the model to choose the user, exposes every tool, and runs generated code in-process.

```mermaid
flowchart LR
    user([User via CLI or DevUI])
    pyrit([PyRIT redteam])

    subgraph compose["Podman Compose, rootless (local only)"]
        chat["chat-api<br/>MAF Agent + AG-UI<br/>no auth, trusts X-User-Id"]
        mcp["health-mcp<br/>13 tools incl. delete_records<br/>user_id is a parameter"]
        report["report-agent (A2A)<br/>exec() generated code<br/>reviewer fails open"]
        cosmos[("Cosmos DB emulator<br/>health + conversations")]
    end

    foundry["Microsoft Foundry<br/>API key"]

    user -->|"AG-UI, no token"| chat
    pyrit -->|"AG-UI"| chat
    chat -->|"MCP, no auth"| mcp
    chat -->|"A2A, untyped JSON"| report
    chat -->|"unbounded history"| cosmos
    mcp --> cosmos
    chat --> foundry
    report --> foundry
```

## Solution components (local)

The solution adds identity, an isolated chart runner, and a governed middleware pipeline. The identity simulator runs only under the `offline` profile ([ADR-0018](adr/0018-offline-identity-simulator.md)).

```mermaid
flowchart LR
    user([alice or bob via CLI])
    devui([DevUI 127.0.0.1<br/>offline mode only])
    pyrit([PyRIT redteam])
    entra["Microsoft Entra ID<br/>Agent ID Blueprint<br/>chat + report agent identities"]
    foundry["Microsoft Foundry<br/>DefaultAzureCredential"]

    subgraph compose["Podman Compose, rootless"]
        subgraph chatns["chat-api network namespace (Compose) or replica (Azure)"]
            chat["chat-api<br/>MAF Agent + AGT middleware<br/>JWT validation"]
            sidecar["Entra SDK for AgentID<br/>sidecar on 127.0.0.1 only"]
        end
        mcp["health-mcp<br/>12 read tools<br/>user from token oid"]
        report["report-agent (A2A)<br/>static check, fail-closed reviewer<br/>signed typed messages"]
        runner["chart-runner<br/>no network, read-only, non-root<br/>Unix socket only"]
        cosmos[("Cosmos DB emulator<br/>health, chat_history, audit")]
        issuer["local identity simulator<br/>offline profile only"]
    end

    user -->|"device code"| entra
    user -->|"AG-UI + user token"| chat
    pyrit -->|"AG-UI + user token"| chat
    devui -.-> chat
    chat -->|"OBO request"| sidecar
    sidecar -->|"token exchange"| entra
    chat -->|"MCP + OBO token"| mcp
    chat -->|"A2A + agent token + signature"| report
    report -->|"Unix socket"| runner
    chat --> cosmos
    mcp --> cosmos
    chat --> foundry
    report --> foundry
    issuer -.->|"offline mode replaces Entra"| chat
```

## Identity flow (ASI03)

The MCP server derives the user from the on-behalf-of token, so a hijacked agent cannot request another user's data ([ADR-0013](adr/0013-entra-agent-id-obo.md), [ADR-0014](adr/0014-agent-id-sidecar.md)). The sidecar accepts loopback callers only, so in Compose it shares chat-api's network namespace, the same topology as the Container Apps replica; no other service can reach it.

```mermaid
sequenceDiagram
    autonumber
    actor Alice as alice (CLI)
    participant Entra as Microsoft Entra ID
    participant Chat as chat-api
    participant Sidecar as AgentID sidecar
    participant MCP as health-mcp
    participant DB as Cosmos DB

    Alice->>Entra: Device code sign-in (scope api://blueprint/access_as_user)
    Entra-->>Alice: User token (aud = Blueprint, oid = alice)
    Alice->>Chat: AG-UI request + user token
    Chat->>Chat: Validate issuer, audience, scope
    Chat->>Sidecar: GET /AuthorizationHeader/HealthMcp?AgentIdentity=chat-agent
    Sidecar->>Entra: OBO exchange as chat agent identity
    Entra-->>Sidecar: MCP token (aud = MCP, scp = Health.Read, oid = alice, azp = chat-agent)
    Sidecar-->>Chat: Authorization header
    Chat->>MCP: get_sleep_by_date(date) + MCP token
    MCP->>MCP: Validate audience, scope, azp
    MCP->>DB: Query WHERE userId = token oid
    DB-->>MCP: alice's records only
    MCP-->>Chat: Result (no free-text notes)
```

## Control placement on the request path

Each control sits at a point where it can fail closed ([ADR-0019](adr/0019-fail-closed-control-contract.md)). All agent middleware attaches to the `Agent`, so DevUI and AG-UI are governed identically ([ADR-0012](adr/0012-demo-clients.md)).

```mermaid
flowchart TD
    req([AG-UI request]) --> auth["JWT validation<br/>ASI03"]
    auth --> kill["Kill switch, per-user quarantine, token budget<br/>fixed reply, no model call<br/>ASI10, ASI08"]
    kill --> input["Input guard<br/>AGT prompt injection + blocked patterns<br/>ASI01"]
    input --> memory["History provider + MemoryGuard<br/>caps, TTL, per-user partition<br/>ASI06"]
    memory --> model["Model call<br/>hash-pinned tiered prompt<br/>ASI01, ASI09"]
    model --> toolpolicy["Tool policy<br/>allowlist, deny, args, session budget<br/>ASI02"]
    toolpolicy --> resilience["Resilience<br/>timeouts, retries, circuit breaker, per-user MCP session, degraded reply<br/>ASI08"]
    resilience --> tools["MCP tools (OBO) or report agent (A2A, approval required)<br/>ASI03, ASI07, ASI09"]
    tools --> result["Tool result guard<br/>abort on injection<br/>ASI01"]
    result --> model
    model --> output["Output guard<br/>clinical advice classifier<br/>ASI09"]
    output --> audit["Hash-chained audit trail + per-user rogue detection<br/>ASI10"]
    audit --> resp([AG-UI response])

    startup(["Startup checks<br/>prompt hash, MCP descriptor lock<br/>ASI01, ASI04"]) -.-> model
```

## Report generation (ASI05, ASI07, ASI09)

Generated chart code never runs in the report agent process ([ADR-0016](adr/0016-isolated-chart-runner.md)). From `s3-reports`, the A2A request is typed and carries an app-only `Report.Generate` token from the chat agent identity (the sidecar's autonomous route). From `s5-supply-chain`, every request also carries a single-use Ed25519 signature from chat-api over the method, path, body hash, nonce, signing time, and schema version; the report agent checks the token first, then the signature (60 s window, in-process replay cache), then the versioned schema. The private key is held by chat-api only (a Compose volume locally, a Container Apps secret on Azure) and the report agent holds only the public key. Every chat reply also passes the fail-closed output guard ([ADR-0021](adr/0021-output-policy-for-clinical-advice.md)), and an approval resume may only approve or reject, never edit the arguments.

```mermaid
sequenceDiagram
    autonumber
    actor User as alice (CLI)
    participant Chat as chat-api
    participant Report as report-agent
    participant Runner as chart-runner or Dynamic Sessions
    participant Reviewer as reviewer (fresh context)

    User->>Chat: "Generate a sleep report"
    Chat-->>User: Approval request (approval_mode = always_require)
    User->>Chat: Approve
    Chat->>Report: Signed, typed A2A request + Report.Generate token
    Report->>Report: Verify token, azp, signature, nonce, timestamp, schema
    Report->>Report: Generate chart code, AST allowlist check
    Report->>Runner: Code over Unix socket (or session pool)
    Runner-->>Report: PNG only (no network, no secrets, size capped)
    Report->>Reviewer: Review report
    alt approved
        Reviewer-->>Report: approved
        Report-->>Chat: Report artefact
    else error, timeout, or rejected
        Reviewer-->>Report: denied
        Report-->>Chat: Status denied, no artefact
    end
```

## Azure deployment

Two apps have external ingress. chat-api serves the AG-UI endpoint, and chat-ui serves the static Vue build of the browser client ([ADR-0025](adr/0025-browser-chat-client.md)). chat-ui holds no tokens server-side and no secrets: the browser signs in with MSAL.js through the `biotrackr-demo-spa` app and calls chat-api directly. chat-api's CORS policy allows only the chat-ui origin, for `POST`, without credentials, and every call still needs a valid user token. The sidecar runs inside the chat API container app and authenticates with a federated credential on the Blueprint ([ADR-0017](adr/0017-live-azure-segment.md)).

```mermaid
flowchart LR
    cli([CLI / PyRIT])
    browser([Browser])
    entra["Microsoft Entra ID<br/>Blueprint + FIC for managed identity<br/>demo CLI and SPA apps"]

    subgraph rg["Resource group (azd)"]
        subgraph cae["Container Apps environment"]
            subgraph chatapp["chat-api app (external ingress)"]
                chat["chat-api container"]
                sidecar["AgentID sidecar container"]
            end
            ui["chat-ui app (external ingress)<br/>nginx, static Vue build, CSP"]
            mcp["health-mcp app<br/>internal ingress"]
            report["report-agent app<br/>internal ingress"]
        end
        sessions["Dynamic Sessions pool<br/>custom container, egress disabled"]
        mi["User-assigned managed identity"]
        reportmi["Report agent managed identity<br/>Foundry, ACR pull, Session Executor"]
        uimi["UI managed identity<br/>ACR pull only"]
        cosmos[("Cosmos DB<br/>Entra auth only")]
        foundry["Microsoft Foundry"]
        appconfig["App Configuration<br/>kill switch"]
        acr["Container Registry"]
        logs["Log Analytics + App Insights<br/>App Insights: managed identity, no GenAI content"]
    end

    cli -->|"HTTPS + user token"| chat
    browser -->|"HTTPS: static files"| ui
    browser -->|"HTTPS + user token, CORS"| chat
    browser -->|"MSAL sign-in"| entra
    chat --> sidecar
    sidecar --> entra
    chat --> mcp
    chat --> report
    report --> sessions
    mi -.-> chat
    mi -.-> mcp
    reportmi -.-> report
    reportmi -.-> sessions
    uimi -.-> ui
    chat --> cosmos
    mcp --> cosmos
    chat --> foundry
    report --> foundry
    chat --> appconfig
    acr -.-> cae
    cae -.-> logs
```

## Telemetry flow and control correlation

[ADR-0026](adr/0026-genai-telemetry-export.md) adds one telemetry bootstrap per stack for chat-api, health-mcp, and report-agent. MAF supplies the GenAI operation, tool, model, and token metadata. FastAPI instruments the built chat app; health probes are excluded.

```mermaid
flowchart LR
    chat["chat-api<br/>HTTP + MAF GenAI spans"]
    mcp["health-mcp<br/>MCP SERVER span"]
    report["report-agent<br/>ASGI outside authentication"]
    local["MAF OTLP exporters<br/>Compose: both stacks"]
    aspire["Aspire Dashboard<br/>UI 127.0.0.1:18888 only"]
    distro["Azure Monitor Distro<br/>Azure: solution only"]
    appi["Application Insights<br/>Entra-only ingestion"]
    audit["Hash-chained Cosmos audit<br/>trace_id inside hashed data"]

    chat -->|"MCP _meta traceparent"| mcp
    chat -->|"Signed A2A + traceparent header"| report
    chat & mcp & report --> local
    local -->|"OTLP/gRPC, internal network"| aspire
    chat & mcp & report --> distro
    distro -->|"Managed identity + Monitoring Metrics Publisher"| appi
    chat -->|"Sanitised biotrackr.control span events"| local
    chat --> audit
```

The solution fixes content capture off in both branches. The starter fixes it on and exports only to local Aspire; an App Insights connection string is ignored with a warning. Neither OTLP port is published to the host. The solution dashboard keeps token login and its read-only hardening. Both stacks use port 18888, so bring one down before starting the other.

MCP server spans extract `_meta` rather than HTTP-session headers: MAF injects context before its MCP client span, making the server span a child of `execute_tool`. A2A uses global httpx injection and outermost ASGI extraction, so a rejected 401 is still traced without changing any signature input.

One HTTP invocation has one distributed trace. A report approval resumes as another invocation: the fetch leg has chat/MCP spans and the approved-report leg has chat/report-agent spans. chart-runner remains uninstrumented and network-less; neither the browser nor the CLI is instrumented by this slice.

Each audit write during a trace stores the trace ID in hash-covered `data` and adds one allowlisted `biotrackr.control` event. User oids stay out of spans. The background Cosmos drain starts in an empty context. Azure exports no application log lines: the distro's logger is dedicated and empty. The default 5-traces/s sampler can omit burst traces, so the audit and scorecards remain separate evidence.

## Risk-to-control map

| ASI     | Starter weakness                                                     | Solution control                                                                                                                                            | Live   |
| ------- | -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| ASI01   | Prompt inline, poisoned notes reach the model                        | Hash-pinned tiered prompt, input and tool-result screening, notes withheld                                                                                  | Yes    |
| ASI02   | All tools incl. delete, unbounded paging, no budget                  | Allowlist, deny `*delete*`, argument validation, atomic session budget                                                                                      | Yes    |
| ASI03   | Model chooses `user_id`, no auth, API keys                           | Entra Agent ID OBO, `oid`-scoped queries, `azp` checks, managed identity                                                                                    | Yes    |
| ASI04   | Unpinned ranges, overridable tool descriptions                       | Hash-locked dependencies, MCP descriptor pinning, digest-pinned images, Dependabot, CodeQL, SBOM, `mcp-scan`                                                | No     |
| ASI05   | `exec()` in the report agent                                         | AST check plus isolated runner with no network or secrets                                                                                                   | Yes    |
| ASI06   | Unbounded history, sessions not bound to users                       | History caps, TTL, per-user partitions, MemoryGuard                                                                                                         | No     |
| ASI07   | Unauthenticated untyped A2A                                          | Agent ID token, single-use Ed25519 signatures with nonce, timestamp, and body hash, versioned typed schemas                                                 | No     |
| ASI08   | No timeouts, outage hangs the agent                                  | Timeouts, bounded retries, circuit breaker, graceful degradation                                                                                            | No     |
| ASI09   | Medical advice allowed, fail-open reviewer                           | Output classifier, fail-closed reviewer, approval for reports, disclaimers                                                                                  | Yes    |
| ASI10   | No audit or kill switch; sensitive telemetry visible in local Aspire | Hash-chained audit, rogue detection, kill switch; metadata-only App Insights export with managed identity, control span events, trace ID in the audit chain | No     |

## Delivery slices

The architecture is built up in vertical slices. Each one ends in a git tag that runs locally and, from S1 onwards, on Azure ([ADR-0023](adr/0023-vertical-slices-with-tagged-checkpoints.md)).

| Tag                 | Starter components                             | Solution components added                                                              | Azure resources added                                                            |
| ------------------- | ---------------------------------------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `s0-foundation`     | chat-api, health-mcp, Cosmos emulator          | None                                                                                   | None                                                                             |
| `s1-identity`       | No change                                      | JWT validation, AgentID sidecar, OBO, identity simulator                               | Container Apps, ACR, managed identity, Cosmos DB, Foundry, monitoring            |
| `s2-tools`          | `delete_records`, rug-pull descriptions        | Governance policies, input, tool, and tool-result guards                               | None (`azd deploy`)                                                              |
| `s3-reports`        | report-agent with `exec()`                     | report-agent, chart-runner, output guard, approvals                                    | report-agent app, Dynamic Sessions pool                                          |
| `s4-operations`     | No change                                      | Memory guard, resilience, kill switch, audit, rogue detection                          | App Configuration, `chat_history` and `audit` containers                         |
| `s5-supply-chain`   | No change                                      | Signed A2A messages, `a2a-keys` service, CI workflows                                  | None (`azd up` for the new signing-key parameters)                               |
| `s6-talk-ready`     | No change                                      | Demo runbook, saved scorecards, one retry for a cold kill-switch read                  | None (`azd deploy`)                                                              |
| `s7-browser-ui`     | No change                                      | Vue browser client, chat-api CORS allowlist, SPA app registration                      | chat-ui app with an AcrPull-only identity (`azd up`)                             |
| `s8-observability`  | Local Aspire with content-visible GenAI traces | Metadata-only distributed traces, control events, hashed audit trace IDs, local Aspire | Two App Insights writer assignments and health-mcp ingestion settings (`azd up`) |

The S8 checkpoint tag marks the validated S8 commit. The live rehearsal of its ASI10 trace contrast is still to come.

## Related documents

* [Architecture decision records](adr/README.md)
* [Demo runbook](demo-runbook.md)
* [Research](research.md)
* [Requirements](requirements.md)
* [Talk abstract](abstract.md)
