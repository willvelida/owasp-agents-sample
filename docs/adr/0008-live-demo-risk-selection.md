---
title: "ADR-0008: Demonstrate five risks live on stage"
description: Select ASI01, ASI02, ASI03, ASI05, and ASI09 for live demonstration and cover the rest through code and PyRIT results
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

The talk is 25 minutes. Demonstrating all ten risks live is not feasible.

## Decision

Demonstrate ASI01 (goal hijack through a poisoned food note), ASI02 (tool misuse), ASI03 (another user's data), ASI05 (code execution in chart generation), and ASI09 (clinical advice and fail-open review) live. Show ASI04, ASI06, ASI07, ASI08, and ASI10 as code and PyRIT scorecard results.

## Consequences

### Positive

* Each live demo has a visible before-and-after moment
* The report agent and its runner become first-tier work

### Negative

* Five live demos in 25 minutes leaves little slack for recovery

## Alternatives considered

| Alternative              | Reason not chosen                               |
|--------------------------|-------------------------------------------------|
| Three or four live demos | Recommended for timing, but the user chose five |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
