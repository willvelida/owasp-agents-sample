---
title: "ADR-0004: Make the starter naive but plausible"
description: Write starter weaknesses as realistic developer shortcuts rather than deliberately planted vulnerabilities
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

Capture-the-flag style vulnerable apps are easy to dismiss as unrealistic. The talk's message lands harder when the insecure code looks like something a reasonable developer would ship.

## Decision

Every starter weakness is a plausible shortcut. Examples include `user_id` as a tool parameter, an allowlist that logs instead of blocks, a reviewer that approves on error, `exec()` for chart code, `>=` dependency ranges, and an API key for the model. Each one is still exploitable for its ASI risk.

## Consequences

### Positive

* Attendees recognise their own code
* Exploits require realistic prompts, not contrived inputs

### Negative

* Some exploits depend on model behaviour and need deterministic canaries to score reliably

## Alternatives considered

| Alternative                           | Reason not chosen                       |
|---------------------------------------|-----------------------------------------|
| Deliberately vulnerable CTF-style app | Maximally exploitable but less credible |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
