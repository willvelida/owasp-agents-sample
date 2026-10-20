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

## Amendment (2026-10-19, slice S3)

Implemented as a MAF chat middleware (`middleware/output_guard.py`), the outermost chat middleware after the input guard. For streams it sets `stream_buffer_updates = True`, appends an async result transform, and sets `stream_result_to_updates`, so neither the client nor the history sees any text before the verdict. The classifier is a fresh, tool-less `Agent` on a separate Foundry client per check, sees only the last user message and the reply (both as untrusted data), and must answer `{"verdict": "safe"}` exactly; anything else is treated as indeterminate. Turns that carry only tool calls are not classified. Azure AI Content Safety custom categories were not used.
