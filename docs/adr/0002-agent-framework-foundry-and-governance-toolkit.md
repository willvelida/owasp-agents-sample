---
title: "ADR-0002: Use Microsoft Agent Framework, Microsoft Foundry, and Agent Governance Toolkit"
description: Build the agent on Microsoft Agent Framework with Foundry models and apply runtime governance with Agent Governance Toolkit
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

The requirements mandate Microsoft Agent Framework (MAF) and Agent Governance Toolkit (AGT). The reference implementation, Biotrackr.Chat.Api, is a C# MAF agent with twelve MCP tools and an A2A reporting agent. MAF Python 1.22.0 is GA and exposes agent, function, and chat middleware. AGT 5.0.0 on PyPI ships a native MAF adapter built on `GovernancePolicy`, which differs from the ACS and Rego API on GitHub `main`.

## Decision

* Build the chat agent with MAF Python (`Agent`, `@tool`, `MCPStreamableHTTPTool`, AG-UI hosting).
* Use Microsoft Foundry through `FoundryChatClient` as the model provider.
* Keep the reporting agent as a separate A2A service with an independent reviewer, matching the C# design.
* Apply AGT 5.0.0 through `create_governance_middleware` with policy values loaded from versioned YAML, not inline Python.
* Pin AGT to the published 5.0.0 API and treat the GitHub `main` ACS engine as future work.

## Consequences

### Positive

* Every runtime control plugs into one middleware pipeline
* The Python sample maps one-to-one onto the C# control story told in the talk
* Policy files are diffable and reviewable

### Negative

* AGT is Public Preview, so APIs may change before the talk
* The ACS engine ships only a Linux x86_64 wheel, which forces Linux containers

## Alternatives considered

| Alternative                  | Reason not chosen                                   |
|------------------------------|-----------------------------------------------------|
| Semantic Kernel or LangGraph | Not permitted by the requirements                   |
| AGT ACS manifests with Rego  | Not available in the published wheel and Linux-only |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
* [Research: Microsoft Agent Framework](../research.md#microsoft-agent-framework-python)
* [Research: Agent Governance Toolkit](../research.md#agent-governance-toolkit)
