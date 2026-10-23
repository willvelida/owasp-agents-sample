---
title: "ADR-0026: Export metadata-only GenAI telemetry with a local content contrast"
description: Export distributed agent traces to Aspire locally and Entra-only Application Insights on Azure, correlate control events with the audit chain, and add slice S8
ms.date: 2026-10-23
ms.topic: reference
---

## Status

Accepted on 2026-10-23 (slice S8). Amends [ADR-0023](0023-vertical-slices-with-tagged-checkpoints.md) by adding S8.

## Context

Microsoft Agent Framework (MAF) already creates GenAI spans, but neither stack installed an exporter. The Azure solution had an Application Insights connection string without ingestion permissions. MCP request metadata and A2A HTTP headers also needed server-side trace extraction.

The ASI10 contrast must show why telemetry is a data boundary: the starter exposes synthetic health records in a local trace, while the solution exports operational metadata without prompts, tool arguments, health records, or user oids. The existing descriptor lock, A2A signatures, chart-runner isolation, and Entra-only ingestion must remain intact.

## Decision

* Each stack has one [telemetry bootstrap](../../solution/src/telemetry/__init__.py), called once at startup by chat-api, health-mcp, and report-agent. Their service names are `biotrackr-chat-api`, `biotrackr-health-mcp`, and `biotrackr-report-agent`. chart-runner remains uninstrumented and network-less.
* On Azure, the solution uses the Azure Monitor OpenTelemetry Distro with each service's user-assigned `ManagedIdentityCredential`, the existing connection string, and Live Metrics. Both app identities have Monitoring Metrics Publisher scoped to Application Insights; the UI identity does not. `DisableLocalAuth: true` is unchanged.
* The distro exports only a dedicated, empty logger, `biotrackr.telemetry.export`. Application log lines are not exported. Control visibility comes from span events rather than forwarding potentially sensitive warnings.
* The distro retains its default 5-traces/s rate-limited sampler. High-volume scorecard runs can lose traces without changing scorecard results. No GenAI-only metric views are installed, so HTTP metrics remain available.
* In Compose, both stacks export OTLP/gRPC to an Aspire Dashboard on the internal network. Only its UI is published, at `127.0.0.1:18888`. The solution keeps token login, a read-only filesystem, dropped capabilities, and no-new-privileges. The starter allows anonymous UI access. Traces are held in memory and disappear when the dashboard stops.
* Aspire uses `13.6.1`: the approved `13.6.2` tag was not published, and the user approved this version-only exception. The solution pins the multi-platform index digest so AMD64 CI and ARM64 hosts select the appropriate image; the starter uses the tag alone.
* The solution's fixed `SENSITIVE_DATA=False` reaches both export branches. The starter's mirrored [bootstrap](../../starter/src/telemetry/__init__.py) sets `True` as its marked ASI10 weakness. It is OTLP-only, has no Azure Monitor dependency, and warns once when ignoring an App Insights connection string. Starter telemetry is never sent to Azure.
* FastAPI is instrumented on the built app, not through a global class replacement. HTTP health URLs are excluded. Export is batched; losing the dashboard does not prevent a normal chat response.
* [TracedFastMCP](../../solution/src/health_mcp/tracing.py) extracts W3C context from MCP `_meta` and creates a `tools/call <tool>` SERVER span with MCP and GenAI operation metadata, without arguments or results. MAF injects metadata before opening its MCP client span, so the server parent is the agent's `execute_tool` span, not the MCP client span. Solution failures record only the exception type.
* Outermost ASGI middleware continues A2A trace headers before bearer and signature validation, including 401 rejections. Global httpx instrumentation injects `traceparent` into fresh A2A clients without changing the signature input or verification headers. It also sends trace context to Foundry, Entra, and identity endpoints; that header carries random correlation IDs, not the user's oid.
* A report approval ends one HTTP invocation and resumes in another. The activity-fetch leg has chat/MCP spans; the approved-report leg has chat/report-agent spans. These two distributed traces are the accepted report scenario, rather than adding client instrumentation to force one trace across the approval pause.
* [AuditTrail.log](../../solution/src/chat_api/middleware/audit.py) stamps the current trace ID inside hashed `data` after sanitisation and emits one `biotrackr.control` event using an explicit scalar-field allowlist. The event excludes oid, session, trace ID, and values containing the current user's oid. The Cosmos audit drain starts in an empty context so its background writes do not inherit the first request.
* `biotrackr.control.*` is an application-owned convention, not a standard GenAI guardrail event. No `gen_ai.evaluation.result` is emitted. Never call AGT `enable_otel()`: it replaces the global provider rather than extending the configured exporter.
* Azure SDK instrumentation stays on. The first deployed warm-up's Cosmos spans were inspected before the other prompts: no query values or document content appeared. If future SDK changes expose values, disable the distro's `azure_sdk` instrumentation and revalidate before continuing.
* This is S8 under the same checkpoint rules as ADR-0023. Its local annotated tag is `s8-observability`, created only after validation, the operator's live rehearsal, and the final commit. Tags are never moved or pushed automatically.

| Slice   | Starter                                        | Solution                                                       | Azure change                                                       | Tag                |
| ------- | ---------------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------ | ------------------ |
| S8      | Local Aspire with content-visible GenAI traces | Metadata-only distributed traces and audit/control correlation | Two telemetry writer assignments and health-mcp ingestion settings | `s8-observability` |

## Consequences

### Positive

* The audience can compare actual content-visible starter telemetry with metadata-only solution telemetry.
* MCP and A2A propagation show service boundaries, including rejected A2A requests, without changing descriptors or signatures.
* Audit trace IDs are persisted and hash-covered; editing the stored ID breaks chain verification.
* An in-memory exporter test exercises real governance and GenAI spans, with a content-enabled positive control proving the no-content check can fail.
* The deployed privacy queries find no GenAI content, user identifiers, exception text, or application log lines. Both managed identities can ingest without enabling local auth.

### Negative

* The distro adds instrumentations for frameworks this application does not use. SDK `1.45.x` and instrumentation `0.66bx` upgrades must remain aligned with exact solution pins and a hash-locked environment.
* Aspire is in-memory, both stacks share port 18888, and OTLP ingestion is unauthenticated inside the container network. Stack switching and keeping starter traces alive require care.
* Portal rendering and ingestion latency are not stage guarantees. The first warm-up request took about 183 seconds to ingest; a later warm request took about 13 seconds. The demo opens already-captured traces and keeps Live Metrics, transaction search, and screenshots as fallbacks.
* Approval produces two invocation traces. Automatic HTTP instrumentation can also include long-lived MCP-session work in the first trace, so the presenter should explain agent/tool spans rather than treating the entire transaction timeline as one model-call duration.
* The sampler can omit traces during bursts. Telemetry is operational evidence, not a replacement for the hash-chained audit or cumulative scorecards.

## Alternatives considered

| Alternative                                              | Reason not chosen                                                                               |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Container Apps managed OpenTelemetry agent               | Requires local auth for this App Insights route and does not provide the required metrics path  |
| Native OTLP through a collector and data collection rule | Adds resources and roles without the same App Insights APM experience                           |
| Azure Monitor exporters alone                            | Smaller dependency footprint, but more manual instrumentation and no selected Live Metrics path |
| Foundry portal tracing                                   | Deferred while Entra ingestion and custom-agent registration remain preview concerns            |
| Jaeger                                                   | Useful raw spans, but no selected GenAI content visualizer                                      |
| Phoenix or Langfuse                                      | Additional deployment/licensing or multi-container complexity for a short local contrast        |
| Header-only MCP propagation                              | The HTTP session task is outside the tool span; MCP `_meta` carries the correct caller context  |
| AGT `enable_otel()`                                      | Replaces the provider with one that has no configured exporter                                  |
| Export starter traces to Azure                           | Violates the local-only boundary for the intentionally content-visible stack                    |

## References

* [ADR-0003: Mirror starter and solution](0003-mirrored-starter-and-solution.md)
* [ADR-0004: Keep the starter naive but plausible](0004-naive-but-plausible-starter.md)
* [ADR-0005: Keep the starter local only](0005-starter-local-only-solution-on-azure.md)
* [ADR-0023: Vertical slices and checkpoints](0023-vertical-slices-with-tagged-checkpoints.md)
* [Architecture](../architecture.md)
* [Demo runbook](../demo-runbook.md)
* [Azure Monitor OpenTelemetry configuration](https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-configuration)
* [Aspire standalone dashboard](https://aspire.dev/dashboard/standalone/)
* [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
