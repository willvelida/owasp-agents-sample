---
title: "ADR-0009: Use the Cosmos DB vNext emulator for local development"
description: Run the Linux Cosmos DB vNext emulator with Podman Compose for both stacks
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

Health data and conversation history live in Azure Cosmos DB. Conference Wi-Fi is unreliable, and the local demo must not depend on a cloud database.

## Decision

Both Compose files run the Cosmos DB vNext emulator with a one-shot seed job. The solution uses Entra-only Cosmos DB on Azure. The emulator key is used only when `COSMOS_EMULATOR=true`.

## Consequences

### Positive

* Fully offline local demo
* Identical data for both stacks

### Negative

* Emulator feature gaps (TTL, connection mode) must be verified in the Phase 0 spikes

## Alternatives considered

| Alternative                        | Reason not chosen          |
|------------------------------------|----------------------------|
| Shared Azure dev Cosmos DB account | Network-dependent on stage |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
