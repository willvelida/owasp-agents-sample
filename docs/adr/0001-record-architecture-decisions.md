---
title: "ADR-0001: Record architecture decisions"
description: Use lightweight architecture decision records to capture design choices for the OWASP Agentic Top 10 sample
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

The sample is built in ten days for a conference talk. Many decisions trade security depth against demo reliability and schedule. Reviewers, attendees, and future contributors need to understand why each trade-off was made, and the talk itself references several of these choices.

## Decision

Record each significant decision as a numbered Markdown ADR in `docs/adr/`. Each record has a status, context, decision, consequences, alternatives, and references. Superseded records stay in place with their status updated and a link to the replacement.

## Consequences

### Positive

* Decision rationale is reviewable alongside the code
* Talk slides can link directly to the reasoning behind each control

### Negative

* Records need updating when open questions from the Phase 0 spikes change a decision

## Alternatives considered

| Alternative                             | Reason not chosen                                                                              |
|-----------------------------------------|------------------------------------------------------------------------------------------------|
| Keep decisions only in the planning log | Planning files under `.copilot-tracking/` are agent working files, not published documentation |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
