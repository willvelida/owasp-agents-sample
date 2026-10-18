---
title: "ADR-0017: Include a live Azure segment in the talk"
description: Demonstrate the solution running on Azure Container Apps during the talk in addition to the local stack
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

The talk promises infrastructure and architecture decisions, not only code. Managed identity, Agent ID federation, internal ingress, and egress-disabled sessions are only visible on Azure.

## Decision

Build an Azure walking skeleton early, in parallel with solution hardening, then reach parity for all five live demos. The runbook includes an Azure segment and warms the environment before the talk.

## Consequences

### Positive

* Shows production-grade identity and network controls
* Validates that controls hold outside Compose

### Negative

* Depends on venue network
* Adds deployment work to an already tight schedule

## Alternatives considered

| Alternative                            | Reason not chosen                                            |
|----------------------------------------|--------------------------------------------------------------|
| Azure as a repository deliverable only | Recommended in review, but the user chose to present it live |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
