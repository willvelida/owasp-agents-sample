---
title: "ADR-0019: Enforce a fail-closed contract for every solution control"
description: Define the required failure behaviour and test for each control type so that no control fails open
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

In MAF, ordinary exceptions in function middleware fail open, and `MiddlewareTermination` may not stop sibling calls in a parallel tool batch. The C# reference documents a fail-open reviewer and a log-only allowlist.

## Decision

Every solution control follows this contract and has a test for it.

| Control type                             | Required behaviour                                |
|------------------------------------------|---------------------------------------------------|
| Inbound authentication                   | 401 or 403 before any session or model call       |
| Input screening                          | Terminate before any model or tool call           |
| Tool result screening                    | Abort the run before the result reaches the model |
| Unknown tool, denied tool, budget breach | Abort the whole tool batch                        |
| MCP argument validation                  | Return an error without querying the database     |
| Prompt or MCP descriptor hash mismatch   | Process exits and never becomes ready             |
| Reviewer error, timeout, or bad verdict  | Persist `denied` and return no artefact           |
| Output policy error or timeout           | Replace the reply with a fixed refusal            |
| Kill switch on                           | Refuse every run before the model call            |

The Phase 0 spikes confirm which MAF mechanism aborts a parallel tool batch. Session budgets are keyed by user and session and incremented atomically.

## Consequences

### Positive

* Closes both documented C# gaps on stage
* Failures are safe by construction and proven by tests

### Negative

* Fail-closed controls can block legitimate requests during outages

## Alternatives considered

| Alternative       | Reason not chosen              |
|-------------------|--------------------------------|
| Log-only controls | This is the starter's weakness |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
* [Research: Microsoft Agent Framework](../research.md#microsoft-agent-framework-python)
