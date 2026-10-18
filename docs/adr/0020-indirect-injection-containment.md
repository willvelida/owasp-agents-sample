---
title: "ADR-0020: Contain indirect prompt injection from tool results"
description: Withhold free-text user notes from the agent and screen every tool result before it reaches the model
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

The ASI01 live demo uses a poisoned food note. Delimiters, length caps, and prompt instructions to treat tool output as data are not a security boundary.

## Decision

* The MCP server never returns free-text `notes`. Results carry `has_note: true` only.
* `tool_result_guard.py` screens every tool result with the AGT prompt-injection detector and versioned blocked patterns, and aborts the run on detection.
* Clean results are wrapped in a data envelope.
* Input screening and a hash-pinned tiered system prompt add further layers.

## Consequences

### Positive

* The poisoned note cannot reach the model in the solution
* Tests prove zero subsequent tool calls after detection

### Negative

* Users cannot see their own notes through the agent until a quarantined summariser is added

## Alternatives considered

| Alternative                          | Reason not chosen                             |
|--------------------------------------|-----------------------------------------------|
| Delimiter wrapping with a length cap | Not a boundary                                |
| Tool-less quarantined summariser     | Stronger usability; tracked as follow-on work |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
