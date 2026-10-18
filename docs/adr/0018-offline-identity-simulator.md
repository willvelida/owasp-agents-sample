---
title: "ADR-0018: Provide an offline identity simulator as a stage fallback"
description: Ship a clearly labelled local token issuer that mimics the Entra token shape for offline demos only
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

The primary ASI03 demo depends on Entra. If venue connectivity fails, the demo still needs per-user tokens. A local issuer that mints tokens for any user is not a security boundary.

## Decision

* `solution/src/local_issuer/` issues alice and bob tokens and mimics the OBO exchange with the same claim shape.
* It is labelled as a stage-only identity simulator.
* It runs only under the Compose `offline` profile, bound to `127.0.0.1`.
* It refuses to start when any Azure environment marker is present, and it is never referenced by Azure artefacts (CI enforces this).
* Each service loads exactly one issuer at startup and rejects tokens from the other.

## Consequences

### Positive

* The demo survives a network outage
* Same data and claims as the Entra path

### Negative

* Anyone on the machine can mint tokens in offline mode

## Alternatives considered

| Alternative                | Reason not chosen                                        |
|----------------------------|----------------------------------------------------------|
| A real local OIDC provider | Too much work before the talk; tracked as follow-on work |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
