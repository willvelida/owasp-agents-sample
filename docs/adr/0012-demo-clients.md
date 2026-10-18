---
title: "ADR-0012: Drive demos through an AG-UI CLI client, DevUI, and PyRIT"
description: Use a shared command-line AG-UI client for authenticated demos, DevUI for local visuals, and PyRIT for attacks
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

DevUI runs the agent in-process and cannot carry per-user tokens, so it cannot demonstrate ASI03. The AG-UI endpoint behaves the same locally and on Azure Container Apps.

## Decision

* Build a shared CLI in `client/` with `--as alice|bob` and `--target starter|solution-local|solution-azure`. It renders tool calls, arguments, and approval prompts.
* The CLI verifies that the token's user matches `--as` to prevent cross-user cache reuse.
* Use DevUI only locally, bound to `127.0.0.1`, in the offline identity mode.
* Attach governance middleware to the `Agent` itself so DevUI and AG-UI are governed identically.

## Consequences

### Positive

* One client for local and Azure demos
* Tool calls and approvals are visible to the audience

### Negative

* Less polished than a web UI

## Alternatives considered

| Alternative           | Reason not chosen             |
|-----------------------|-------------------------------|
| DevUI only            | Cannot show per-user identity |
| Custom AG-UI web chat | Too much work before the talk |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
