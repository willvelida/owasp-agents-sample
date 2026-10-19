---
title: "ADR-0014: Acquire agent tokens through the Entra SDK for AgentID sidecar"
description: Run the Microsoft Entra SDK for AgentID as a sidecar locally and on Azure and restrict its network reach
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

Python has no first-party Agent ID library. The Microsoft Entra SDK for AgentID container performs OBO and autonomous token acquisition over HTTP. Its unauthenticated endpoints make it a credential broker for anything that can reach it.

## Decision

* Locally, run the sidecar in Compose inside `chat-api`'s network namespace (`network_mode: service:chat-api`), listening on `127.0.0.1:5000` only. No published port; a dev client secret on the Blueprint.
* On Azure, run it as a second container in the chat API container app, using a federated identity credential on the Blueprint for the user-assigned managed identity.
* Configure only the chat agent's identity as usable, and test that other services cannot connect.

Amended on 2026-10-18 (slice S1): the sidecar rejects non-loopback callers (HTTP 403) outside the Development environment, so the original dedicated `sidecar-net` plus egress network could not work. Sharing chat-api's namespace matches the Container Apps replica and leaves no network path from other services. The published image is amd64 only, so Compose builds it from a pinned upstream commit for arm64 hosts; Azure uses the MCR image.

## Consequences

### Positive

* The same token flow locally and on Azure
* No secrets in the Azure deployment

### Negative

* The local dev secret must be stored outside source control
* One more container to operate

## Alternatives considered

| Alternative                               | Reason not chosen                          |
|-------------------------------------------|--------------------------------------------|
| Hand-rolled `fmi_path` exchange with MSAL | More code and more room for error          |
| Agent ID on Azure only                    | Loses the identity story in the local demo |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
* [Microsoft Entra SDK for AgentID](https://learn.microsoft.com/entra/msidweb/agent-id-sdk/overview)
