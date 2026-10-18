---
title: "ADR-0021: Screen agent replies for clinical advice"
description: Classify final agent replies and replace unsafe or indeterminate ones with a fixed refusal
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

A tiered system prompt alone is unlikely to withstand multi-turn Crescendo attacks for diagnosis and medication advice. The report reviewer protects reports only, not ordinary chat replies.

## Decision

`output_guard.py` buffers the final reply and classifies it with a tool-less model call that returns a JSON verdict, or with Azure AI Content Safety custom categories if available. An unsafe or indeterminate verdict, an error, or a five-second timeout replaces the reply with a fixed Tier-4 refusal and disclaimer.

## Consequences

### Positive

* ASI09 is enforced on every reply
* Behaviour under classifier failure is safe

### Negative

* Buffering removes token streaming for final replies
* Adds latency and model cost per turn

## Alternatives considered

| Alternative                        | Reason not chosen                      |
|------------------------------------|----------------------------------------|
| System prompt only                 | Bypassable                             |
| Content Safety Prompt Shields only | Targets injection, not clinical advice |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
