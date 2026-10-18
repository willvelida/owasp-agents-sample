---
title: "ADR-0005: Run the starter locally only and deploy the solution to Azure"
description: Restrict the intentionally insecure starter to local Podman Compose and deploy only the solution with azd and Bicep
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

The starter executes model-generated code, exposes a delete tool, and has no authentication. Deploying it to a public endpoint creates real risk to the subscription and tenant.

## Decision

The starter has a Compose file run with `podman compose` and no application infrastructure code. Its only Azure dependency is a model: `starter/model/main.bicep` creates a Foundry account and `gpt-4.1` deployment in a separate resource group, `rg-owasp-agents-starter-model`, with no starter code deployed. The solution has a Compose file plus `azure.yaml` and Bicep for Azure Container Apps. The root README carries a caution that the starter must never be deployed.

## Consequences

### Positive

* No internet-exposed insecure agent
* Less infrastructure to maintain

### Negative

* Starter-versus-solution comparisons on Azure are not possible; the comparison happens locally

## Alternatives considered

| Alternative                 | Reason not chosen                                 |
|-----------------------------|---------------------------------------------------|
| Deploy both stacks to Azure | Exposes an `exec()`-capable unauthenticated agent |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
