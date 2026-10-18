---
title: "ADR-0007: Deliver all ten controls before the talk with prioritised cut lines"
description: Implement controls for all ten OWASP Agentic risks plus Azure deployment before the talk, ordered by priority tiers
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18. The tiered schedule was amended the same day by [ADR-0023](0023-vertical-slices-with-tagged-checkpoints.md), which replaces tiers with vertical slices. The scope decision stands.

## Context

Plan review flagged the scope as large for ten days. The user chose to keep all ten controls, `azd` deployment, and a live Azure segment in scope.

## Decision

Implement all ten controls before 2026-10-28. Work is ordered by demo value as vertical slices (see [ADR-0023](0023-vertical-slices-with-tagged-checkpoints.md)). If a date slips, the latest unfinished slice is dropped or trimmed, never an earlier one, and the drop is logged. The five live-demo risks are complete by slice S3.

## Consequences

### Positive

* The repository covers the full OWASP list the talk promises
* A slip degrades scope predictably instead of breaking the demo

### Negative

* High schedule risk
* Later slices may land after the talk

## Alternatives considered

| Alternative                                              | Reason not chosen                           |
|----------------------------------------------------------|---------------------------------------------|
| Conference scope of five live risks plus a later release | Recommended in review, declined by the user |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
