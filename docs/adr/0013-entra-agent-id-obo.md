---
title: "ADR-0013: Use Entra Agent ID on-behalf-of flow for user-scoped tool access"
description: Bind health data access to the signed-in user through an Entra Agent ID on-behalf-of token exchange
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

The core ASI03 weakness is that the model chooses whose data to read. Forwarding a user claim from the agent still lets a compromised agent assert any user. An on-behalf-of (OBO) token cryptographically binds the downstream call to the signed-in user and to the agent's own identity.

## Decision

* Users alice and bob sign in to the CLI with device code, requesting `api://{blueprint}/access_as_user`.
* The chat API validates the token and exchanges it through the Agent ID sidecar for an MCP-audience token, with `AgentIdentity` set to the chat agent.
* The MCP server validates audience, `Health.Read` scope, and the calling agent (`azp`), then filters every query by the token's `oid`. `user_id` is removed from all tool signatures.
* The report API is called with an app-only Agent ID token carrying the `Report.Generate` role.

## Consequences

### Positive

* A hijacked agent still cannot read another user's data
* Each agent instance has a distinct, auditable identity

### Negative

* Requires a real Entra tenant, test users, and tenant-wide consent
* Adds a dependency on network access to Entra during the live demo

## Alternatives considered

| Alternative                                           | Reason not chosen                                                                            |
|-------------------------------------------------------|----------------------------------------------------------------------------------------------|
| Autonomous Agent ID token with a forwarded user claim | MCP still trusts the agent to assert the user; retained as the shape of the offline fallback |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
* [Microsoft Entra Agent ID setup](https://learn.microsoft.com/entra/agent-id/identity-platform/agent-id-setup-instructions)
