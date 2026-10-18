---
title: "ADR-0010: Use an API key in the starter and Entra ID in the solution for model access"
description: Authenticate to Microsoft Foundry with an API key in the starter and DefaultAzureCredential in the solution
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

Static API keys are a common shortcut and an ASI03 weakness. The solution should demonstrate keyless access with managed identity.

## Decision

The starter reads `FOUNDRY_API_KEY` from `.env` and uses its own key-enabled Foundry resource. The solution uses a separate Foundry resource with key auth disabled (`disableLocalAuth: true`) and authenticates with `DefaultAzureCredential`, which resolves to managed identity on Azure. The solution never falls back to an API key. The local container credential mechanism is covered by [ADR-0022](0022-local-azure-credential-in-compose.md).

## Consequences

### Positive

* A visible ASI03 contrast
* No long-lived model secret in the solution

### Negative

* The solution needs RBAC on the Foundry resource for the developer and the managed identity

## Alternatives considered

| Alternative              | Reason not chosen                           |
|--------------------------|---------------------------------------------|
| Entra ID for both stacks | Removes an easy-to-explain starter weakness |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
