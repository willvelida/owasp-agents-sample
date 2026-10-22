---
title: "ADR-0012: Drive demos through an AG-UI CLI client, DevUI, and PyRIT"
description: Use a shared command-line AG-UI client for authenticated demos, DevUI for local visuals, and PyRIT for attacks
ms.date: 2026-10-22
ms.topic: reference
---

## Status

Accepted on 2026-10-18. Amended on 2026-10-22 by [ADR-0025](0025-browser-chat-client.md).

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

## Amendment (2026-10-22, slice S7)

[ADR-0025](0025-browser-chat-client.md) adds a text-only Vue browser client for the solution, with its own Entra SPA registration. It replaces the "Custom AG-UI web chat" rejection above for the solution segment only:

* The browser is the solution segment's demo surface. It shows alice and bob side by side and the ASI09 approval as a dialog.
* The CLI stays the client for the starter segment and the red team, and it is the verbatim recovery path when the browser fails on stage.
* DevUI stays local-only, bound to `127.0.0.1` in the offline identity mode. CI fails if `solution/infra` or `solution/azure.yaml` references it.
